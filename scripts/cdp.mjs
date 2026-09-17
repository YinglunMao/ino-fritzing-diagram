/**
 * cdp.mjs — Chrome DevTools Protocol 极简客户端（零依赖，Node 22+ 原生 WebSocket）
 *
 * 能力：
 *   discover()            自动找到可用的 CDP 入口（用户 Chrome / 自启 headless Chrome / web-access 代理）
 *   page(CDP)  .goto()    新建后台 tab 并导航，不打断用户已开的标签
 *             .eval()     在页面里执行 JS，返回 JSON 化的结果
 *             .shot()     截图到本地文件
 *             .close()    关掉自己创建的 tab
 *
 * CLI:
 *   node cdp.mjs check                                  探测可用入口
 *   node cdp.mjs eval --url <url> --expr <js> [--wait 2000] [--shot out.png]
 *   node cdp.mjs shot --url <url> --file out.png [--width 1600 --height 1000 --wait 1500]
 *                       （对 file:// 的 SVG 光栅化，用于自检生成结果）
 */

import { spawn } from 'node:child_process';
import { existsSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';

const CHROME_CANDIDATES = [
  // macOS
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
  // Linux
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
  // Windows
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
];
const PROBE_PORTS = [9222, 9229, 9333, 9334];
const WS_TIMEOUT = 9000; // 本机 Chrome 的 devtools WS 握手实测可能耗时 ~5s，不能设太短

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 取「第一个成功」的结果，全部失败则返回 null */
function firstSuccess(promises) {
  return new Promise((resolve) => {
    let left = promises.length;
    if (!left) return resolve(null);
    let settled = false;
    for (const p of promises) {
      Promise.resolve(p)
        .then((v) => {
          if (!settled && v) {
            settled = true;
            resolve(v);
          }
        })
        .catch(() => {})
        .finally(() => {
          if (--left <= 0 && !settled) resolve(null);
        });
    }
  });
}

async function httpJson(url, timeout = 1200) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(url, { signal: ctl.signal });
    if (!r.ok) return null;
    const txt = await r.text();
    return txt ? JSON.parse(txt) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

/** 探测 WebSocket 入口是否真的可用（有些端点不提供 HTTP /json） */
async function probeWs(wsUrl, timeout = 2500) {
  return await new Promise((resolve) => {
    let settled = false;
    let ws = null;
    let timer = null;
    const finish = (ok) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      try {
        if (ws) ws.close();
      } catch {}
      resolve(ok);
    };
    timer = setTimeout(() => finish(false), timeout);
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      return finish(false);
    }
    ws.onopen = () => finish(true);
    ws.onerror = () => finish(false);
    ws.onclose = () => finish(false);
  });
}

/** 按需自启一个 headless Chrome（独立 user-data-dir，绝不碰用户浏览器） */
export async function launchChrome(port = 9333) {
  const bin = (process.env.CHROME_PATH && existsSync(process.env.CHROME_PATH))
    ? process.env.CHROME_PATH
    : CHROME_CANDIDATES.find((p) => existsSync(p));
  if (!bin) throw new Error('未找到 Chrome/Chromium/Edge 可执行文件（可用 CHROME_PATH 环境变量显式指定）');
  const profile = mkdtempSync(join(tmpdir(), 'cdp-profile-'));
  const args = [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-background-networking',
    '--hide-scrollbars',
    'about:blank',
  ];
  const child = spawn(bin, args, { detached: true, stdio: 'ignore' });
  child.unref();
  for (let i = 0; i < 60; i++) {
    await sleep(400);
    const ws = await probeWs(`ws://127.0.0.1:${port}/devtools/browser`, 2500);
    if (ws) return { wsUrl: `ws://127.0.0.1:${port}/devtools/browser`, mode: 'launched-headless', pid: child.pid };
  }
  throw new Error(`自启 Chrome 后 ${port} 端口仍不可用`);
}

/**
 * 找到可用的 CDP 入口。
 * 优先级：显式指定 → 用户已开的 Chrome → 自启 headless
 */
export async function discover({ wsUrl, allowLaunch = true, verbose = false } = {}) {
  if (wsUrl) {
    if (!(await probeWs(wsUrl))) throw new Error(`指定的 CDP 入口不可用: ${wsUrl}`);
    return { wsUrl, mode: 'explicit' };
  }
  const probes = [];
  for (const port of PROBE_PORTS) {
    probes.push(
      httpJson(`http://127.0.0.1:${port}/json/version`, 1500).then((v) =>
        v?.webSocketDebuggerUrl ? { wsUrl: v.webSocketDebuggerUrl, mode: `http:${port}`, browser: v.Browser } : null
      )
    );
    probes.push(
      probeWs(`ws://127.0.0.1:${port}/devtools/browser`, WS_TIMEOUT).then((ok) =>
        ok ? { wsUrl: `ws://127.0.0.1:${port}/devtools/browser`, mode: `ws:${port}` } : null
      )
    );
  }
  const found = await firstSuccess(probes);
  if (found) return found;
  if (!allowLaunch) throw new Error('没有可用的 CDP 入口');
  if (verbose) console.error('[cdp] 未发现运行中的调试端口，正在自启 headless Chrome …');
  return await launchChrome(9333);
}

/** 一个极简 CDP 连接 */
export class CDP {
  constructor(ws) {
    this.ws = ws;
    this._id = 0;
    this._pending = new Map();
    this._events = new Map();
    ws.onmessage = (ev) => {
      let m;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.id && this._pending.has(m.id)) {
        this._pending.get(m.id)(m);
        this._pending.delete(m.id);
      } else if (m.method) {
        const hs = this._events.get(m.method) || [];
        for (const h of hs) h(m.params, m.sessionId);
      }
    };
  }

  static async connect(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      const t = setTimeout(() => rej(new Error('CDP WebSocket 连接超时')), 8000);
      ws.onopen = () => {
        clearTimeout(t);
        res();
      };
      ws.onerror = () => {
        clearTimeout(t);
        rej(new Error('CDP WebSocket 连接失败: ' + wsUrl));
      };
    });
    return new CDP(ws);
  }

  on(method, handler) {
    if (!this._events.has(method)) this._events.set(method, []);
    this._events.get(method).push(handler);
  }

  send(method, params = {}, sessionId) {
    const id = ++this._id;
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => {
        this._pending.delete(id);
        reject(new Error(`CDP 超时: ${method}`));
      }, 90000);
      this._pending.set(id, (m) => {
        clearTimeout(t);
        if (m.error) reject(new Error(`${method}: ${m.error.message}`));
        else resolve(m.result);
      });
      this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  }

  async close() {
    try {
      this.ws.close();
    } catch {}
  }
}

/** 打开一个后台标签页（bg:true 不抢焦点，不打扰用户正在浏览的内容） */
export async function openPage(cdp, url = 'about:blank', { bg = true } = {}) {
  const { targetId } = await cdp.send('Target.createTarget', { url, background: bg });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  await cdp.send('Page.enable', {}, sessionId);
  await cdp.send('Runtime.enable', {}, sessionId);
  return new PageHandle(cdp, targetId, sessionId);
}

class PageHandle {
  constructor(cdp, targetId, sessionId) {
    this.cdp = cdp;
    this.targetId = targetId;
    this.sid = sessionId;
  }

  async goto(url, { waitMs = 0 } = {}) {
    await this.cdp.send('Page.navigate', { url }, this.sid);
    if (waitMs) await sleep(waitMs);
    return this;
  }

  /** 等待页面加载完成（最多 timeout 毫秒） */
  async waitLoaded(timeout = 15000) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      try {
        const { result } = await this.cdp.send(
          'Runtime.evaluate',
          { expression: 'document.readyState', returnByValue: true },
          this.sid
        );
        if (result.value === 'complete' || result.value === 'interactive') return true;
      } catch {}
      await sleep(200);
    }
    return false;
  }

  /** 轮询直到 expr 求值为真；返回 {ok, value} */
  async waitFor(expr, { timeout = 20000, interval = 500 } = {}) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      const v = await this.eval(`(()=>{try{return JSON.stringify(${expr})}catch(e){return '"ERR"'} })()`);
      if (v && v !== 'ERR' && v !== false && v !== 'false' && v !== 'null') return { ok: true, value: v };
      await sleep(interval);
    }
    return { ok: false };
  }

  /** 执行 JS，返回已反序列化的值 */
  async eval(expression, { awaitPromise = false } = {}) {
    const { result, exceptionDetails } = await this.cdp.send(
      'Runtime.evaluate',
      { expression, returnByValue: true, awaitPromise },
      this.sid
    );
    if (exceptionDetails) throw new Error('页面内 JS 异常: ' + (exceptionDetails.text || '') + ' ' + (exceptionDetails.exception?.description || ''));
    return result?.value;
  }

  async setViewport(width, height, deviceScaleFactor = 2) {
    await this.cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor, mobile: false }, this.sid);
  }

  async shot(file, { fullPage = true } = {}) {
    mkdirSync(dirname(file), { recursive: true });
    let clip;
    if (fullPage) {
      const m = await this.cdp.send('Page.getLayoutMetrics', {}, this.sid);
      const cs = m.cssContentSize || m.contentSize;
      if (cs && cs.width && cs.height) {
        clip = { x: 0, y: 0, width: Math.ceil(cs.width), height: Math.ceil(cs.height), scale: 1 };
      }
    }
    const { data } = await this.cdp.send(
      'Page.captureScreenshot',
      { format: 'png', captureBeyondViewport: fullPage, ...(clip ? { clip } : {}) },
      this.sid
    );
    const { writeFileSync } = await import('node:fs');
    writeFileSync(file, Buffer.from(data, 'base64'));
    return file;
  }

  async close() {
    try {
      await this.cdp.send('Target.closeTarget', { targetId: this.targetId });
    } catch {}
  }
}

// ------------------------------------------------------------------ CLI
async function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  const opt = {};
  for (let i = 1; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const k = argv[i].slice(2);
      const v = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : true;
      opt[k] = v;
    }
  }

  if (cmd === 'check' || !cmd) {
    try {
      const d = await discover({ wsUrl: opt.ws, verbose: true });
      console.log(JSON.stringify({ ok: true, ...d }, null, 2));
    } catch (e) {
      console.log(JSON.stringify({ ok: false, error: e.message }, null, 2));
      process.exit(1);
    }
    return;
  }

  const d = await discover({ wsUrl: opt.ws });
  const cdp = await CDP.connect(d.wsUrl);
  try {
    if (cmd === 'eval') {
      const p = await openPage(cdp, opt.url || 'about:blank');
      await p.waitLoaded();
      if (opt.wait) await sleep(Number(opt.wait));
      await p.waitFor('document.readyState === "complete"', { timeout: 15000 });
      const v = await p.eval(opt.expr || 'document.title');
      console.log(typeof v === 'string' ? v : JSON.stringify(v, null, 2));
      if (opt.shot) {
        await p.setViewport(1600, 1000, 1);
        await p.shot(opt.shot);
        console.error('[cdp] screenshot ->', opt.shot);
      }
      await p.close();
    } else if (cmd === 'shot') {
      const w = Number(opt.width || 1600);
      const h = Number(opt.height || 1000);
      const p = await openPage(cdp, 'about:blank');
      await p.setViewport(w, h, Number(opt.scale || 2));
      await p.goto(opt.url, { waitMs: Number(opt.wait || 1200) });
      await p.waitLoaded();
      await sleep(Number(opt.wait || 1200));
      await p.shot(opt.file, { fullPage: opt.full !== 'false' });
      console.log(opt.file);
      await p.close();
    } else {
      console.error('未知命令:', cmd);
      process.exit(2);
    }
  } finally {
    await cdp.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((e) => {
    console.error('[cdp] ERROR:', e.message);
    process.exit(1);
  });
}
