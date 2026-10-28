// @ts-check
'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

/** @type {typeof import('./lib/dex-buddy-sdk')} */
const sdk = require('./lib/dex-buddy-sdk');
const { childEnv, requireEntitlement } = sdk;

/**
 * @typedef {{ info: (msg: string) => void; error: (msg: string) => void }} Logger
 * @typedef {{ python?: string; env?: NodeJS.ProcessEnv }} PluginRuntime
 * @typedef {{ data?: string }} PluginDirs
 * @typedef {{
 *   logger: Logger;
 *   registerService: (name: string, service: Record<string, Function>) => void;
 *   pluginEnv?: () => NodeJS.ProcessEnv;
 *   dirs?: PluginDirs;
 *   runtime?: PluginRuntime;
 * }} AppContext
 * @typedef {{
 *   apply: (ctx: AppContext) => void | Promise<void>;
 *   dispose?: () => void | Promise<void>;
 * }} PluginModule
 * @typedef {{ resolve: (value: unknown) => void; reject: (reason?: unknown) => void }} PendingWaiter
 * @typedef {{ id?: unknown; ok?: unknown; error?: unknown; code?: unknown; result?: unknown }} WorkerMessage
 */

const ROOT = __dirname;
const NOT_READY = '运行环境还没准备好';
const SETTING_KEYS = /** @type {const} */ ([
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'MINIMAX_API_KEY',
]);

/**
 * @param {unknown} payload
 * @returns {Record<string, unknown>}
 */
function asObject(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return {};
  return /** @type {Record<string, unknown>} */ (payload);
}

/**
 * @param {unknown} params
 * @returns {string}
 */
function splitWith(params) {
  const value = asObject(params).split_with;
  return typeof value === 'string' ? value : '';
}

/**
 * @param {{ data?: string } | null | undefined} dirs
 * @param {string} [fallback]
 * @returns {string}
 */
function prepareDataRoot(dirs, fallback) {
  const dataRoot = dirs && dirs.data ? dirs.data : (fallback || ROOT);
  fs.mkdirSync(path.join(dataRoot, 'temp'), { recursive: true });
  fs.mkdirSync(path.join(dataRoot, 'output'), { recursive: true });
  return dataRoot;
}

/**
 * @param {NodeJS.ProcessEnv | null | undefined} baseEnv
 * @param {NodeJS.ProcessEnv | null | undefined} pluginEnv
 * @param {string} root
 * @param {string} [dataRoot]
 * @returns {NodeJS.ProcessEnv}
 */
function workerEnv(baseEnv, pluginEnv, root, dataRoot) {
  const env = Object.assign({}, baseEnv || {}, pluginEnv || {});
  env.PYTHONUNBUFFERED = '1';
  env.MANJU_ROOT = root;
  env.MANJU_DATA_ROOT = dataRoot || root;
  const lib = path.join(root, 'lib');
  const current = env.PYTHONPATH || '';
  env.PYTHONPATH = current ? `${lib}${path.delimiter}${current}` : lib;
  return env;
}

/**
 * @param {NodeJS.ProcessEnv | null | undefined} env
 * @returns {Record<string, string>}
 */
function settingValues(env) {
  /** @type {Record<string, string>} */
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

/**
 * @param {{ python?: string } | null | undefined} runtime
 * @returns {{ error: string } | { command: string; args: string[] }}
 */
function resolveWorker(runtime) {
  const python = runtime && runtime.python;
  if (typeof python !== 'string' || !python) return { error: NOT_READY };
  return { command: python, args: ['-m', 'src.studio.hub_worker'] };
}

/**
 * @param {string} method
 * @param {unknown} params
 * @returns {boolean}
 */
function needsEntitlement(method, params) {
  if (method === 'createJob') return true;
  if (method === 'preview') return splitWith(params) === 'model';
  return false;
}

/** @type {AppContext | null} */
let pluginCtx = null;
/** @type {import('child_process').ChildProcess | null} */
let child = null;
/** @type {import('readline').Interface | null} */
let reader = null;
/** @type {Logger | null} */
let logger = null;
let stopped = false;
let seq = 0;
let queue = Promise.resolve();
/** @type {Map<string, PendingWaiter>} */
const pending = new Map();

/**
 * @param {string} message
 */
function logError(message) {
  if (logger && typeof logger.error === 'function') {
    logger.error(message);
    return;
  }
  console.error(message);
}

/**
 * @param {string} message
 */
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
  } catch {
    // 管道已经结束时 close 可能抛错，后面没有人再读这一条输出。
  }
}

/**
 * @returns {NodeJS.ProcessEnv}
 */
function currentPluginEnv() {
  if (pluginCtx && typeof pluginCtx.pluginEnv === 'function') {
    return pluginCtx.pluginEnv();
  }
  return process.env;
}

/**
 * @param {unknown} raw
 * @returns {WorkerMessage | null}
 */
function parseWorkerMessage(raw) {
  try {
    const parsed = JSON.parse(String(raw));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    return /** @type {WorkerMessage} */ (parsed);
  } catch {
    return null;
  }
}

/**
 * @param {WorkerMessage} message
 * @returns {Error & { code?: string }}
 */
function rejectWorker(message) {
  const text = typeof message.error === 'string' && message.error ? message.error : '执行失败';
  const err = /** @type {Error & { code?: string }} */ (new Error(text));
  if (typeof message.code === 'string' && message.code) {
    err.code = message.code;
  }
  return err;
}

async function ensureChild() {
  if (stopped) {
    throw new Error('插件已卸载');
  }
  if (child && child.exitCode === null && !child.killed) {
    return;
  }
  const runtime = pluginCtx && pluginCtx.runtime;
  const resolved = resolveWorker(runtime);
  if ('error' in resolved) {
    throw new Error(resolved.error);
  }
  const dataRoot = prepareDataRoot(pluginCtx && pluginCtx.dirs, ROOT);
  // runtime.env 已带虚拟环境和设置。常驻进程的环境停在启动时，密钥改动靠每条请求再带一份。
  const baseEnv = runtime && runtime.env ? runtime.env : {};
  closeReader();
  const env = await childEnv(pluginCtx, workerEnv(baseEnv, null, ROOT, dataRoot));
  const proc = spawn(resolved.command, resolved.args, {
    cwd: ROOT,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  const stdout = proc.stdout;
  if (!stdout) {
    proc.kill();
    throw new Error('插件进程启动失败');
  }
  child = proc;
  reader = readline.createInterface({ input: stdout });
  reader.on('line', (line) => {
    const message = parseWorkerMessage(line);
    if (!message) {
      logError(line);
      return;
    }
    const waiter = pending.get(String(message.id));
    if (!waiter) return;
    pending.delete(String(message.id));
    if (message.ok) waiter.resolve(message.result);
    else waiter.reject(rejectWorker(message));
  });
  if (proc.stderr) {
    proc.stderr.on('data', (chunk) => {
      const text = String(chunk).trim();
      if (text) logError(text);
    });
  }
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

/**
 * @param {string} method
 * @param {unknown} params
 */
function callWorker(method, params) {
  const run = async () => {
    await ensureChild();
    const proc = child;
    const stdin = proc && proc.stdin;
    if (!proc || !stdin) {
      throw new Error('插件进程启动失败');
    }
    return new Promise((resolve, reject) => {
      const id = String(++seq);
      pending.set(id, { resolve, reject });
      stdin.write(JSON.stringify({
        id,
        method,
        params: asObject(params),
        settings: settingValues(currentPluginEnv()),
      }) + '\n');
    });
  };
  // 一次只写一行，避免两条大响应在同一条管道里交错。
  const next = queue.then(run, run);
  queue = next.then(() => {}, () => {});
  return next;
}

/**
 * @param {string} method
 */
function bind(method) {
  /**
   * @param {unknown} params
   */
  return function run(params) {
    return callWorker(method, params);
  };
}

/**
 * @param {string} method
 * @param {unknown} params
 */
async function gatedCall(method, params) {
  if (needsEntitlement(method, params)) {
    await requireEntitlement(pluginCtx);
  }
  return callWorker(method, params);
}

/**
 * @typedef {PluginModule & {
 *   resolveWorker: typeof resolveWorker;
 *   prepareDataRoot: typeof prepareDataRoot;
 *   workerEnv: typeof workerEnv;
 *   settingValues: typeof settingValues;
 *   needsEntitlement: typeof needsEntitlement;
 * }} ManjuModule
 */

/**
 * @type {ManjuModule}
 */
module.exports = {
  resolveWorker,
  prepareDataRoot,
  workerEnv,
  settingValues,
  needsEntitlement,
  /**
   * @param {AppContext} ctx
   */
  apply(ctx) {
    pluginCtx = ctx;
    logger = ctx.logger;
    stopped = false;
    ctx.logger.info('漫剧操作台已挂载');
    ctx.registerService('manjuStudioService', {
      /**
       * @param {unknown} params
       */
      preview: (params) => gatedCall('preview', params),
      /**
       * @param {unknown} params
       */
      createJob: (params) => gatedCall('createJob', params),
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
