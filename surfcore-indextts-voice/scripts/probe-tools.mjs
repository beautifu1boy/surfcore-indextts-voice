#!/usr/bin/env node
// 直接跟 SurfCore 的 snowluma MCP server 握手，打印它实际注册了哪些工具。
//
// 用来回答一个反复出现的问题：「她的工具表里到底有没有 qq_send_voice？」
// MCP 的工具清单在 server 进程启动时确定，改完 config.json 不重启 DSH 是不会变的——
// 这个脚本读的是**当前磁盘配置**，所以能提前告诉你会不会再出现"她不会说话"。
//
// 用法：
//   node scripts/probe-tools.mjs [--repo <SurfCore 目录>]
//
// 退出码：0 = 有语音工具；1 = 没有（配置没开 / 文件不存在）
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const i = args.indexOf('--repo');
const repo = path.resolve(
  i >= 0 && args[i + 1]
    ? args[i + 1]
    : process.env.SURFCORE_DIR || path.join(process.env.USERPROFILE || process.env.HOME || '.', 'Documents', 'surfcore'),
);
const serverPath = path.join(repo, 'src', 'mcp-snowluma-safe.js');
const configPath = path.join(repo, 'config.json');

if (!fs.existsSync(serverPath)) {
  console.error(`找不到 ${serverPath}\n用 --repo <SurfCore 目录> 指定。`);
  process.exit(2);
}

// 先自己读一遍配置，把结论先摆出来（比握手快，也更好懂）
if (fs.existsSync(configPath)) {
  const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8').replace(/^\uFEFF/, ''));
  const voiceOn = cfg?.socialV2?.voice?.enabled !== false;
  const ttsOn = cfg?.socialV2?.voice?.tts?.enabled !== false;
  const toolOn = cfg?.socialV2?.tools?.sendVoice !== false;
  console.log('配置:');
  console.log(`  socialV2.voice.enabled        = ${voiceOn}`);
  console.log(`  socialV2.voice.tts.enabled    = ${ttsOn}`);
  console.log(`  socialV2.tools.sendVoice      = ${toolOn}`);
  console.log(`  socialV2.voice.tts.character  = ${JSON.stringify(cfg?.socialV2?.voice?.tts?.character ?? '')}`);
  if (!voiceOn || !toolOn) {
    console.log('\n=> 语音工具不会被注册。把上面两个 false 改成 true，然后重启 DSH。');
  }
  console.log('');
}

const child = spawn(process.execPath, [serverPath], { cwd: repo, stdio: ['pipe', 'pipe', 'inherit'] });
let buf = '';
const pending = new Map();
child.stdout.on('data', (d) => {
  buf += d.toString('utf8');
  let idx;
  while ((idx = buf.indexOf('\n')) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  }
});

let nextId = 1;
function rpc(method, params) {
  const id = nextId++;
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error(`timeout: ${method}`)), 15000);
    pending.set(id, (m) => { clearTimeout(t); resolve(m); });
  });
}

try {
  await rpc('initialize', {
    protocolVersion: '2024-11-05',
    capabilities: {},
    clientInfo: { name: 'surfcore-tool-probe', version: '1.0.0' },
  });
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  const res = await rpc('tools/list', {});
  const names = (res.result?.tools ?? []).map((t) => t.name);
  const voice = names.filter((n) => /voice/i.test(n));
  console.log(`MCP 注册工具总数: ${names.length}`);
  console.log(`语音相关: ${voice.length ? voice.join(', ') : '(无)'}`);
  if (voice.length) {
    console.log('\n=> 正常。DSH 重启过的话，她就能用 qq_send_voice 了。');
    process.exitCode = 0;
  } else {
    console.log('\n=> 没有语音工具。检查上面的配置，改完必须重启 DSH。');
    process.exitCode = 1;
  }
} catch (e) {
  console.error(`握手失败：${e.message}`);
  process.exitCode = 2;
} finally {
  child.kill();
  setTimeout(() => process.exit(process.exitCode ?? 0), 200);
}
