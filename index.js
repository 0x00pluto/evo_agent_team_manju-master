const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const ROOT = __dirname;
const NOT_READY = '运行环境还没准备好';
const SETTING_KEYS = [
  'DEEPSEEK_API_KEY',
  'DEEPSEEK_BASE_URL',
  'DEEPSEEK_MODEL',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'MINIMAX_API_KEY',
];

function prepareDataRoot(dirs, fallback) {
  const dataRoot = dirs && dirs.data ? dirs.data : (fallback || ROOT);
  fs.mkdirSync(path.join(dataRoot, 'temp'), { recursive: true });
  fs.mkdirSync(path.join(dataRoot, 'output'), { recursive: true });
  return dataRoot;
}

function workerEnv(baseEnv, pluginEnv, root, dataRoot) {
  const env = Object.assign({}, baseEnv || {}, pluginEnv || {});
  env.PYTHONUNBUFFERED = '1';
  env.MANJU_ROOT = root;
  env.MANJU_DATA_ROOT = dataRoot || root;
  return env;
}

function settingValues(env) {
  const out = {};
  if (!env) return out;
  for (const key of SETTING_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(env, key)) continue;
    const value = env[key];
    if (value === undefined || value === null) continue;
    out[key] = String(value);
  }
  return out;
}

function resolveWorker(runtime) {
  const python = runtime && runtime.python;
  if (!python) return { error: NOT_READY };
  return { command: python, args: ['-m', 'src.studio.hub_worker'] };
}

let pluginCtx = null;
let child = null;
let reader = null;
let logger = null;
let stopped = false;
let seq = 0;
let queue = Promise.resolve();
const pending = new Map();

function logError(message) {
  if (logger && typeof logger.error === 'function') {
    logger.error(message);
    return;
  }
  console.error(message);
}

function failPending(message) {
  for (const waiter of pending.values()) {
    waiter.reject(new Error(message));
  }
  pending.clear();
}

function closeReader() {
  if (!reader) return;
  const current = reader;
  reader = null;
  try {
    current.close();
  } catch (err) {
    // 管道已经结束时 close 可能抛错，后面没有人再读这一条输出。
  }
}

function currentPluginEnv() {
  if (pluginCtx && typeof pluginCtx.pluginEnv === 'function') {
    return pluginCtx.pluginEnv();
  }
  return process.env;
}

function ensureChild() {
  if (stopped) {
    throw new Error('插件已卸载');
  }
  if (child && child.exitCode === null && !child.killed) {
    return;
  }
  const runtime = pluginCtx && pluginCtx.runtime;
  const resolved = resolveWorker(runtime);
  if (resolved.error) {
    throw new Error(resolved.error);
  }
  const dataRoot = prepareDataRoot(pluginCtx && pluginCtx.dirs, ROOT);
  // runtime.env 已带虚拟环境和设置。常驻进程的环境停在启动时，密钥改动靠每条请求再带一份。
  const baseEnv = runtime && runtime.env ? runtime.env : {};
  closeReader();
  const proc = spawn(resolved.command, resolved.args, {
    cwd: ROOT,
    env: workerEnv(baseEnv, null, ROOT, dataRoot),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  child = proc;
  reader = readline.createInterface({ input: proc.stdout });
  reader.on('line', (line) => {
    let message;
    try {
      message = JSON.parse(line);
    } catch (err) {
      logError(line);
      return;
    }
    const waiter = pending.get(String(message.id));
    if (!waiter) return;
    pending.delete(String(message.id));
    if (message.ok) waiter.resolve(message.result);
    else waiter.reject(new Error(message.error || '执行失败'));
  });
  proc.stderr.on('data', (chunk) => {
    const text = String(chunk).trim();
    if (text) logError(text);
  });
  proc.on('error', (err) => {
    if (child === proc) failPending(err && err.message ? err.message : '插件进程启动失败');
  });
  proc.on('exit', () => {
    if (child !== proc) return;
    closeReader();
    child = null;
    failPending('插件进程已退出');
  });
}

function callWorker(method, params) {
  const run = () => new Promise((resolve, reject) => {
    let proc;
    try {
      ensureChild();
      proc = child;
    } catch (err) {
      reject(err);
      return;
    }
    const id = String(++seq);
    pending.set(id, { resolve, reject });
    proc.stdin.write(JSON.stringify({
      id,
      method,
      params: params && typeof params === 'object' ? params : {},
      settings: settingValues(currentPluginEnv()),
    }) + '\n');
  });
  // 一次只写一行，避免两条大响应在同一条管道里交错。
  const next = queue.then(run, run);
  queue = next.then(() => {}, () => {});
  return next;
}

function bind(method) {
  return function run(params) {
    return callWorker(method, params);
  };
}

module.exports = {
  resolveWorker,
  prepareDataRoot,
  workerEnv,
  settingValues,
  apply(ctx) {
    pluginCtx = ctx;
    logger = ctx.logger;
    stopped = false;
    ctx.logger.info('漫剧操作台已挂载');
    ctx.registerService('manjuStudioService', {
      preview: bind('preview'),
      createJob: bind('createJob'),
      getJob: bind('getJob'),
      recent: bind('recent'),
      bench: bind('bench'),
      resynth: bind('resynth'),
      reveal: bind('reveal'),
      readVoice: bind('readVoice'),
      downloadZip: bind('downloadZip'),
      listSlots: bind('listSlots'),
      bindSlot: bind('bindSlot'),
      cloneSlot: bind('cloneSlot'),
      replaceSlot: bind('replaceSlot'),
      addSlot: bind('addSlot'),
      generateVoice: bind('generateVoice'),
    });
  },

  dispose() {
    // 只关掉 worker。plugin-data 留给下次安装，覆盖和卸载都不在这里删。
    stopped = true;
    const proc = child;
    child = null;
    closeReader();
    failPending('插件已卸载');
    if (proc && proc.exitCode === null) {
      proc.kill();
    }
  },
};
