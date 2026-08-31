// test_wifi_web.mjs —— 网页端端到端模拟：加载 web/index.html 的真实 JS，
// 配一个行为与 main.py 一致的假 BLE 设备，验证 WiFi 面板
// （扫描列表渲染 / 点击填入 / 连接成功与失败 / 状态刷新 / 断开 / 忘记 / 热点重配）。
// 运行：node test/test_wifi_web.mjs （需 Node 18+，无需浏览器）
import fs from 'fs';
import vm from 'vm';
import { TextEncoder, TextDecoder } from 'util';

const html = fs.readFileSync(new URL('../web/index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const PWD = '1234';
const b64 = s => Buffer.from(s, 'utf8').toString('base64');

/* ---------- 假设备（行为对齐 main.py 的 WiFi/认证/文件命令） ---------- */
function makeDevice() {
  const dev = {
    name: 'ESP32S3-WIFI',
    gatt: { connected: true },
    _ls: {},
    addEventListener(t, cb) { (this._ls[t] ||= []).push(cb); },
    emit(t) { for (const cb of this._ls[t] || []) cb(); },
  };
  let authed = false, fails = 0;
  const chars = {};
  dev.handleCmd = line => {
    if (!authed && !line.startsWith('AUTH ')) return 'ERR auth required\n';
    if (line.startsWith('AUTH ')) {
      const p = line.slice(5);
      if (p === PWD) { authed = true; fails = 0; return 'AUTH OK\nDONE\n'; }
      fails++;
      const msg = 'ERR auth failed (' + fails + '/3)\n';
      if (fails >= 3) setTimeout(() => { dev.gatt.connected = false; dev.emit('gattserverdisconnected'); }, 5);
      return msg;
    }
    if (line === 'PING') return 'PONG ESP32S3-WIFI 1.0\nDONE\n';
    if (line === 'LIST') return 'F main.py 100\nF config.py 20\nDONE\n';
    if (line === 'WIFI_SCAN') {
      return 'N 3 1 -40 ' + b64('MyWiFi') + '\n' +
             'N 0 6 -70 ' + b64('OpenNet') + '\n' +
             'N 7 11 -55 ' + b64('\u6d4b\u8bd5') + '\nDONE\n';
    }
    if (line.startsWith('WIFI_CONNECT ')) {
      const [, a, p] = line.split(' ');
      const ssid = Buffer.from(a, 'base64').toString('utf8');
      const pwd = Buffer.from(p, 'base64').toString('utf8');
      if (ssid === 'MyWiFi' && pwd === 'goodpass') return 'WIFI connecting MyWiFi\nC 1\nC 2\nWIFI OK 192.168.1.100\nDONE\n';
      return 'WIFI connecting ' + ssid + '\nERR wrong password\n';
    }
    if (line === 'WIFI_DISCONNECT') return 'OK wifi disconnected\nDONE\n';
    if (line === 'WIFI_FORGET') return 'OK wifi forgotten\nDONE\n';
    if (line.startsWith('WIFI_AP ')) return 'OK ap configured\nDONE\n';
    if (line === 'WIFI_STATUS') {
      return 'STA CONNECTED ' + b64('MyWiFi') + ' 192.168.1.100 192.168.1.1 8.8.8.8\n' +
             'AP ' + b64('ESP32S3-AP') + ' 192.168.4.1 0\n' +
             'SAVED ' + b64('MyWiFi') + '\nDONE\n';
    }
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
  TextEncoder, TextDecoder, Blob, URL, atob, btoa, Map, Set,
  confirm: () => true,
  Promise, Date, Math, JSON, Uint8Array, Array, Object, String, Number, Boolean, Symbol,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(script, sandbox);

const flush = () => new Promise(r => setTimeout(r, 40));
let pass = 0, fail = 0;
function expect(name, cond) {
  if (cond) { pass++; console.log('  PASS ' + name); }
  else { fail++; console.log('  FAIL ' + name); }
}
function startConnect() { return vm.runInContext('doConnect()', sandbox); } // 不 await，弹窗等输入

/* ===== 场景 1：连接 + 认证 + 自动刷新 WiFi 状态 ===== */
console.log('\n[场景 1] 连接并认证');
let p1 = startConnect();
await flush();
els.authPwd.value = PWD;
vm.runInContext('submitAuth()', sandbox);
await p1;
await flush();
expect('登录成功', logs.some(l => l.includes('密码验证通过')));
expect('列表已加载', logs.some(l => l.includes('文件列表: 2 项')));
expect('WiFi 状态已刷新（连接后自动）', logs.some(l => l.includes('WiFi 状态已刷新')));
expect('状态面板显示已连接 MyWiFi', (els.wifiStatus.textContent || '').includes('已连接 MyWiFi'));
expect('状态面板显示热点', (els.wifiStatus.textContent || '').includes('热点（AP）'));

/* ===== 场景 2：扫描路由器 ===== */
console.log('\n[场景 2] 扫描路由器');
await vm.runInContext('scanWifi()', sandbox);
await flush();
expect('扫描完成日志', logs.some(l => l.includes('扫描完成: 3 个路由器')));
expect('列表渲染 3 项（含中文 SSID）', els.wifiList._children.length === 3);
const li0 = vm.runInContext('document.getElementById("wifiList")._children[0]', sandbox);
expect('第一项是 MyWiFi', li0._children[0].textContent === 'MyWiFi');
expect('元信息含信号与认证类型', (li0._children[1].innerHTML || '').includes('-40 dBm') && (li0._children[1].innerHTML || '').includes('WPA2'));

/* ===== 场景 3：点击列表项填入 SSID ===== */
console.log('\n[场景 3] 点击扫描结果填入 SSID');
vm.runInContext('document.getElementById("wifiList")._children[0].onclick()', sandbox);
expect('SSID 已填入输入框', els.wifiSsid.value === 'MyWiFi');

/* ===== 场景 4：连接成功 ===== */
console.log('\n[场景 4] 连接路由器成功');
vm.runInContext('document.getElementById("wifiPwd").value = "goodpass"', sandbox);
await vm.runInContext('connectWifi()', sandbox);
await flush();
expect('已连接日志（含 IP）', logs.some(l => l.includes('已连接路由器，IP: 192.168.1.100')));
expect('配置保存提示', logs.some(l => l.includes('路由器配置已保存')));
expect('进度行已显示', logs.some(l => l.includes('连接中 1 秒')));

/* ===== 场景 5：连接失败（错误密码） ===== */
console.log('\n[场景 5] 连接失败（错误密码）');
vm.runInContext('document.getElementById("wifiSsid").value = "MyWiFi"', sandbox);
vm.runInContext('document.getElementById("wifiPwd").value = "bad"', sandbox);
await vm.runInContext('connectWifi()', sandbox);
await flush();
expect('失败日志含原因', logs.some(l => l.includes('连接失败: wrong password')));

/* ===== 场景 6：手动刷新状态 ===== */
console.log('\n[场景 6] 手动刷新状态');
await vm.runInContext('refreshWifiStatus()', sandbox);
await flush();
expect('状态含已保存配置', (els.wifiStatus.textContent || '').includes('已保存配置  : MyWiFi'));

/* ===== 场景 7：断开（保留配置） ===== */
console.log('\n[场景 7] 断开连接（保留配置）');
await vm.runInContext('disconnectWifi()', sandbox);
await flush();
expect('断开日志', logs.some(l => l.includes('已断开（配置保留')));

/* ===== 场景 8：忘记配置 ===== */
console.log('\n[场景 8] 忘记配置');
await vm.runInContext('forgetWifi()', sandbox);
await flush();
expect('忘记日志', logs.some(l => l.includes('已忘记路由器配置')));

/* ===== 场景 9：热点重配 ===== */
console.log('\n[场景 9] 应用热点设置');
vm.runInContext('document.getElementById("apSsid").value = "ESP32S3-AP2"', sandbox);
vm.runInContext('document.getElementById("apPwd").value = "87654321"', sandbox);
await vm.runInContext('applyAp()', sandbox);
await flush();
expect('热点重配日志', logs.some(l => l.includes('热点已重配为 ESP32S3-AP2')));

console.log(`\n结果: ${pass} 通过, ${fail} 失败`);
process.exit(fail ? 1 : 0);
