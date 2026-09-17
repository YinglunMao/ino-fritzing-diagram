/**
 * bing_images.mjs — 通过 Chrome CDP 在 Bing 图片搜索中查元件/开发板外观图，并下载到本地
 *
 * 用法：
 *   node bing_images.mjs --out <dir> --limit 3 \
 *        --q "AS7341 spectral sensor module" --q "MPU6050 GY-521 module"
 *   node bing_images.mjs --out <dir> --spec <spec.json>      # spec: [{slug, name, query}]
 *
 * 输出：
 *   <dir>/<slug>_1.jpg …          下载到的参考图
 *   <dir>/_index.json             {slug: {name, query, images:[{file, src, page, w, h}]}}
 *
 * 说明：
 *   - 用真实 Chrome 渲染 Bing，走用户本机网络/代理；下载用 curl（自动继承 HTTPS_PROXY）
 *   - 只创建后台 tab 并自行关闭，不影响用户已有标签页
 *   - 结果按「域名多样性 + 图片类型」做轻量择优，便于后续视觉判断
 */

import { existsSync, mkdirSync, writeFileSync, renameSync, unlinkSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { discover, CDP, openPage } from './cdp.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function safeUnlink(p) {
  try {
    if (existsSync(p)) unlinkSync(p);
  } catch {}
}

// 电子元件/开发板资料站，命中优先
const GOOD_HOSTS = [
  'adafruit.com', 'arduino.cc', 'dfrobot.com', 'dfrobot.com.cn', 'seeedstudio.com', 'seeed.cc',
  'waveshare.com', 'spotpear.cn', 'spotpear.com', 'components101.com', 'lastminuteengineers.com',
  'randomnerdtutorials.com', 'aliexpress.com', 'amazon.com', 'roboticsdna.in', 'circuitrocks.com',
  'microcontrollerslab.com', 'how2electronics.com', 'instructables.com', 'githubusercontent.com',
  'wiki.seeedstudio.com', 'docs.arduino.cc', 'espressif.com', 'openhacks.com', 'botland.store',
];
const BAD_HINTS = ['sprite', 'favicon', 'placeholder', 'blank.gif', 'spacer', 'pixel.gif', 'logo-bing'];

function hostOf(u) {
  try {
    return new URL(u).host.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function score(item) {
  const host = hostOf(item.murl);
  let s = 0;
  if (GOOD_HOSTS.some((g) => host.endsWith(g))) s += 100;
  if (/\.(jpe?g|png|webp)$/i.test(item.murl)) s += 20;
  if (/\.gif$/i.test(item.murl)) s -= 25; // 动图多为噪声
  if (BAD_HINTS.some((b) => item.murl.toLowerCase().includes(b))) s -= 200;
  if (/bing\.com\/(th|rp)/.test(item.murl)) s -= 300;
  const w = item.w || 0;
  const h = item.h || 0;
  if (w >= 400 && h >= 400) s += 15;
  if (w > 4000 || h > 4000) s -= 10;
  return s;
}

/** 在 Bing 图片页里抓候选图 */
async function searchImages(page, query, { scroll = 2 } = {}) {
  const url = `https://www.bing.com/images/search?q=${encodeURIComponent(query)}&form=HDRSC2&first=1`;
  await page.goto(url, { waitMs: 1200 });
  await page.waitLoaded(20000);

  let list = [];
  for (let i = 0; i < 20; i++) {
    const raw = await page.eval(`(() => {
      const out = [];
      document.querySelectorAll('a.iusc').forEach(el => {
        try {
          const m = JSON.parse(el.getAttribute('m') || '{}');
          if (!m.murl) return;
          const img = el.querySelector('img');
          out.push({ murl: m.murl, turl: m.turl || '', purl: m.purl || '', title: m.t || (img && img.alt) || '' });
        } catch (e) {}
      });
      return JSON.stringify(out);
    })()`);
    list = JSON.parse(raw || '[]');
    if (list.length >= 8) break;
    await sleep(800);
  }
  // 滚动触发懒加载，扩大候选池
  for (let i = 0; i < scroll; i++) {
    await page.eval('window.scrollBy(0, 1800); true');
    await sleep(700);
  }
  const raw2 = await page.eval(`(() => {
    const out = [];
    document.querySelectorAll('a.iusc').forEach(el => {
      try {
        const m = JSON.parse(el.getAttribute('m') || '{}');
        if (m.murl) out.push({ murl: m.murl, turl: m.turl || '', purl: m.purl || '', title: m.t || '' });
      } catch (e) {}
    });
    return JSON.stringify(out);
  })()`);
  const extra = JSON.parse(raw2 || '[]');
  const seen = new Set();
  const all = [...list, ...extra].filter((x) => {
    if (!x.murl || /^data:/.test(x.murl) || seen.has(x.murl)) return false;
    seen.add(x.murl);
    return true;
  });
  return { title: await page.eval('document.title'), items: all };
}

/** 择优 + 域名多样化 */
function pick(items, limit) {
  const ranked = items.map((it) => ({ ...it, _s: score(it) })).sort((a, b) => b._s - a._s);
  const out = [];
  const usedHost = new Set();
  for (const it of ranked) {
    if (it._s < -50) continue;
    const h = hostOf(it.murl);
    if (usedHost.has(h)) continue;
    usedHost.add(h);
    out.push(it);
    if (out.length >= limit) break;
  }
  if (out.length < limit) {
    for (const it of ranked) {
      if (out.includes(it) || it._s < -50) continue;
      out.push(it);
      if (out.length >= limit) break;
    }
  }
  return out;
}

function extFor(file, contentType) {
  const ct = (contentType || '').toLowerCase();
  if (ct.includes('png')) return 'png';
  if (ct.includes('webp')) return 'webp';
  if (ct.includes('gif')) return 'gif';
  if (ct.includes('jpeg') || ct.includes('jpg')) return 'jpg';
  const m = /\.(jpe?g|png|webp|gif)(?:\?|$)/i.exec(file || '');
  return m ? m[1].toLowerCase().replace('jpeg', 'jpg') : 'jpg';
}

function download(url, outBase, { referer = 'https://www.bing.com/' } = {}) {
  // curl 自动继承 HTTPS_PROXY/HTTP_PROXY；-w 输出实际 content-type 以便定扩展名
  const tmp = outBase + '.bin';
  try {
    const res = execFileSync(
      'curl',
      [
        '-sSL', '--max-time', '25', '--compressed',
        '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        '-e', referer,
        '-o', tmp,
        '-w', `%{http_code}|%{content_type}|%{size_download}`,
        url,
      ],
      { encoding: 'utf8' }
    );
    const [code, ct, size] = String(res).split('|');
    if (code !== '200' || Number(size) < 3000 || !/image\//.test(ct)) {
      safeUnlink(tmp);
      return null;
    }
    const finalPath = `${outBase}.${extFor('', ct)}`;
    renameSync(tmp, finalPath);
    return { file: finalPath, contentType: ct, bytes: Number(size) };
  } catch {
    safeUnlink(tmp);
    return null;
  }
}

async function main() {
  const argv = process.argv.slice(2);
  const opt = { out: 'refs', limit: '3', ws: undefined };
  const queries = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--q' || a === '--query') queries.push(argv[++i]);
    else if (a === '--out') opt.out = argv[++i];
    else if (a === '--limit') opt.limit = argv[++i];
    else if (a === '--ws') opt.ws = argv[++i];
    else if (a === '--spec') opt.spec = argv[++i];
    else if (!a.startsWith('--')) queries.push(a);
  }

  let jobs = queries.map((q, i) => ({ slug: slugify(q), name: q, query: q, i }));
  if (opt.spec) {
    const spec = JSON.parse(readFileSync(opt.spec, 'utf8'));
    jobs = (Array.isArray(spec) ? spec : spec.components || []).map((c) => ({
      slug: c.slug || slugify(c.name || c.query),
      name: c.name || c.query,
      query: c.query || c.name,
    }));
  }
  if (!jobs.length) {
    console.error('用法: node bing_images.mjs --out refs --q "AS7341 module" [--q ...] [--limit 3]');
    process.exit(2);
  }

  const dir = resolve(opt.out);
  mkdirSync(dir, { recursive: true });
  const limit = Number(opt.limit);

  const d = await discover({ wsUrl: opt.ws, verbose: true });
  console.error(`[bing] CDP: ${d.mode} ${d.wsUrl}`);
  const cdp = await CDP.connect(d.wsUrl);
  const indexPath = join(dir, '_index.json');
  const index = existsSync(indexPath) ? JSON.parse(readFileSync(indexPath, 'utf8')) : {};

  try {
    for (const job of jobs) {
      const page = await openPage(cdp, 'about:blank');
      try {
        console.error(`[bing] 搜索: ${job.query}`);
        const { title, items } = await searchImages(page, job.query);
        const chosen = pick(items, limit);
        const images = [];
        for (let i = 0; i < chosen.length; i++) {
          const base = join(dir, `${job.slug}_${i + 1}`);
          const r = download(chosen[i].murl, base);
          if (r) images.push({ ...r, src: chosen[i].murl, page: chosen[i].purl, title: chosen[i].title });
          else console.error(`        跳过（下载失败）: ${chosen[i].murl.slice(0, 90)}`);
        }
        index[job.slug] = { name: job.name, query: job.query, pageTitle: title, candidates: items.length, images };
        console.error(`[bing] ${job.slug}: 候选 ${items.length} 张 → 下载 ${images.length} 张`);
      } finally {
        await page.close();
      }
      await sleep(600);
    }
  } finally {
    writeFileSync(indexPath, JSON.stringify(index, null, 2));
    await cdp.close();
  }
  console.log(JSON.stringify(index, null, 2));
}

function slugify(s) {
  return String(s)
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 60);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((e) => {
    console.error('[bing] ERROR:', e.message);
    process.exit(1);
  });
}
