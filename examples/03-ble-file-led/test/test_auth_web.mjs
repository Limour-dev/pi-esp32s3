// test_auth_web.mjs —— 网页端端到端模拟：加载 web/index.html 的真实 JS，
// 配一个行为与 main.py 一致的假 BLE 设备，验证密码认证全流程。
// 运行：node test/test_auth_web.mjs （需 Node 18+，无需浏览器）
import fs from 'fs';
import vm from 'vm';
import { TextEncoder, TextDecoder } from 'util';

const html = fs.readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const PWD = '1234';

/* ---------- 假设备（行为对齐 main.py 认证逻辑） ---------- */
function makeDevice() {
  const dev = {
    name: 'ESP32S3-FS',
    gatt: { connected: true },
    _ls: {},
    addEventListener(t, cb) { (this._ls[t] ||= []).push(cb); },
    emit(t) { for (const cb of this._ls[t] || []) cb(); },
  };
  let authed = false, fails = 0;
  const chars = {};
  dev.handleCmd = line => {
    if (line === 'NEVER') return null; // 测试用：永不响应
    if (!authed && line !== 'AUTH ' + PWD && !line.startsWith('AUTH ')) return 'ERR auth required\n';
    if (line.startsWith('AUTH ')) {
      const p = line.slice(5);
      if (p === PWD) { authed = true; fails = 0; return 'AUTH OK\nDONE\n'; }
      fails++;
      const msg = 'ERR auth failed (' + fails + '/3)\n';
      if (fails >= 3) setTimeout(() => { dev.gatt.connected = false; dev.emit('gattserverdisconnected'); }, 5);
      return msg;
    }
    if (line === 'PING') return 'PONG ESP32S3-FS 1.1\nDONE\n';
    if (line === 'LIST') return 'F main.py 100\nF config.py 20\nDONE\n';
    return 'ERR unknown\nDONE\n';
  };
  dev.gatt.connect = async () => ({
    getPrimaryService: async () => ({
      getCharacteristic: async cuuid => {
        const c = {
          uuid: cuuid, _ls: {},
          addEventListener(t, cb) { (this._ls[t] ||= []).push(cb); },
          startNotifications: async () => {},
          writeValue: async bytes => {
            const line = new TextDecoder().decode(bytes).trim();
            if (cuuid.includes('ffe1')) {
              const resp = dev.handleCmd(line);
              if (!resp) return; // 不回复
              setTimeout(() => {
                for (const l of resp.split('\n')) {
                  if (!l) continue;
                  const ev = { target: { value: new TextEncoder().encode(l + '\n') } };
                  for (const cb of (chars.data?._ls['characteristicvaluechanged'] || [])) cb(ev);
                }
              }, 1);
            }
          },
        };
        if (cuuid.includes('ffe2')) chars.data = c; else if (cuuid.includes('ffe1')) chars.cmd = c;
        return c;
      },
    }),
  });
  dev.gatt.disconnect = () => {
    if (!dev.gatt.connected) return;
    dev.gatt.connected = false;
    dev.emit('gattserverdisconnected');
  };
  return dev;
}

/* ---------- DOM mock ---------- */
const els = {};
function makeEl(id) {
  return {
    id, textContent: '', innerHTML: '', value: '', disabled: false,
    style: {}, className: '', scrollTop: 0, scrollHeight: 0,
    classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
                 contains(c) { return this._s.has(c); } },
    _ls: {}, _children: [],
    addEventListener(t, cb) { (this._ls[t] ||= []).push(cb); },
    appendChild(c) { this._children.push(c); },
    append(...c) { this._children.push(...c); },
    remove() {}, click() {}, focus() {},
  };
}
const document = {
  getElementById: id => (els[id] ||= makeEl(id)),
  createElement: tag => makeEl(tag),
  addEventListener() {},
};
const window = { addEventListener() {} };
const navigator = { bluetooth: { requestDevice: async () => makeDevice() } };

/* ---------- 捕获日志 ---------- */
const logs = [];
els['log'] = makeEl('log');
const origAppendChild = els['log'].appendChild.bind(els['log']);
els['log'].appendChild = c => { logs.push(c.textContent); origAppendChild(c); };

const sandbox = {
  document, window, navigator, console, setTimeout, clearTimeout, setInterval, clearInterval,
  TextEncoder, TextDecoder, Blob, URL, atob, btoa,
  confirm: () => true,
  Promise, Date, Math, JSON, Uint8Array, Array, Object, String, Number, Boolean, Symbol,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

const flush = () => new Promise(r => setTimeout(r, 30));
let pass = 0, fail = 0;
function expect(name, cond) {
  if (cond) { pass++; console.log('  PASS ' + name); }
  else { fail++; console.log('  FAIL ' + name); }
}
function startConnect() { return vm.runInContext('doConnect()', sandbox); } // 不 await，弹窗等输入

/* ===== 场景 1：正确密码 ===== */
console.log('\n[场景 1] 正确密码连接');
let p1 = startConnect();
await flush();
expect('弹窗出现', els.authModal.classList.contains('show'));
els.authPwd.value = PWD;
vm.runInContext('submitAuth()', sandbox);
await p1;
await flush();
expect('登录成功日志', logs.some(l => l.includes('密码验证通过')));
expect('已连接状态', (els.statusText.textContent || '').includes('已连接'));
expect('PING 已发', logs.some(l => l.includes('PING -> PONG ESP32S3-FS 1.1')));
expect('列表已加载', logs.some(l => l.includes('文件列表: 2 项')));
expect('无失败日志', !logs.some(l => l.includes('认证失败')));

/* ===== 场景 2：错误密码 3 次 → 自动断开 ===== */
console.log('\n[场景 2] 错误密码 3 次');
let p2 = startConnect();
await flush();
expect('弹窗出现', els.authModal.classList.contains('show'));
els.authPwd.value = 'wrong';
vm.runInContext('submitAuth()', sandbox);
await flush();
expect('第 1 次失败可重试', logs.some(l => l.includes('认证失败（第 1 次）')) && els.authModal.classList.contains('show'));
els.authPwd.value = 'wrong2';
vm.runInContext('submitAuth()', sandbox);
await flush();
els.authPwd.value = 'wrong3';
vm.runInContext('submitAuth()', sandbox);
await p2;
await flush();
expect('第 3 次失败日志', logs.some(l => l.includes('认证失败（第 3 次）')));
expect('设备已断开并清理', logs.some(l => l.includes('设备已断开连接')));

/* ===== 场景 3：取消认证 ===== */
console.log('\n[场景 3] 取消认证');
let p3 = startConnect();
await flush();
expect('弹窗出现', els.authModal.classList.contains('show'));
vm.runInContext('closeAuthModal()', sandbox);
await p3;
await flush();
expect('取消日志', logs.some(l => l.includes('已取消连接')));
expect('取消后断开清理', logs.some(l => l.includes('设备已断开连接')));

/* ===== 场景 4：断开时挂起请求被 reject（onDisconnected 修复） ===== */
console.log('\n[场景 4] 连接中设备断开，挂起请求应被 reject');
let p4 = startConnect();
await flush();
els.authPwd.value = PWD;
vm.runInContext('submitAuth()', sandbox);
await p4;
await flush();
// 已认证连接建立后，发一个设备永不响应的请求，中途模拟断开
const slowReq = vm.runInContext(`(async () => {
  let settled = 'pending';
  request('NEVER', () => {}, 15000).then(() => settled = 'resolved', () => settled = 'rejected');
  return new Promise(r => setTimeout(() => r(settled), 60));
})()`, sandbox);
await flush();
vm.runInContext('onDisconnected()', sandbox);
const settled = await slowReq;
expect('挂起请求被 reject（页面不卡死）', settled === 'rejected');

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);
