// @ts-check
'use strict';

/**
 * Dex Buddy 插件 SDK 1.0.0。拷进插件 lib/ 后：
 * 工作台走宿主校验与 ctx.models；独立跑 requireEntitlement 直接通过，bindModels 用 DEX_BUDDY_API_KEY（开发者付钱）。
 * 对照文档母版的 SDK_VERSION，不一致就整文件再拷。不要把 Key 写进设置或 zip。
 */

const SDK_VERSION = '1.0.0';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

const DEFAULT_BASE = 'https://www.dexbuddy.app';
const MISSING_KEY =
  '独立运行需要环境变量 DEX_BUDDY_API_KEY（账号里的用户 API Key，dbh_sk_ 开头）。写进本机 .env，不要放进插件设置，也不要打进 zip。装进 Dex Buddy 后会改走宿主，扣使用者的积分。';

class DexModelsError extends Error {
  /**
   * @param {string} code
   * @param {string} message
   * @param {number} [status]
   */
  constructor(code, message, status) {
    super(message);
    this.name = 'DexModelsError';
    this.code = code;
    this.status = typeof status === 'number' ? status : 0;
  }
}

/** @type {Promise<string> | null} */
let proxyUrlPromise = null;

function missingKey() {
  return new DexModelsError('UNAUTHORIZED', MISSING_KEY, 401);
}

/**
 * @typedef {{
 *   list: () => Promise<unknown>;
 *   billing: { quote: (body?: unknown, options?: { idempotencyKey?: string }) => Promise<unknown> };
 *   chat: { completions: { create: (body?: unknown, options?: { idempotencyKey?: string }) => Promise<unknown> } };
 *   images: { generate: (input?: unknown, options?: { idempotencyKey?: string }) => Promise<unknown> };
 * }} HostModels
 */

/**
 * @param {unknown} ctx
 * @returns {HostModels | null}
 */
function hostModels(ctx) {
  const models = ctx && typeof ctx === 'object' ? /** @type {{ models?: HostModels }} */ (ctx).models : null;
  const create = models && models.chat && models.chat.completions && models.chat.completions.create;
  return typeof create === 'function' && models ? models : null;
}

/**
 * @param {unknown} raw
 * @returns {string}
 */
function trimString(raw) {
  return typeof raw === 'string' ? raw.trim() : '';
}

/**
 * @param {Record<string, unknown> | null | undefined} [options]
 */
function resolvePluginId(options) {
  const fromOptions = trimString(options && /** @type {{ pluginId?: string }} */ (options).pluginId);
  if (fromOptions) return fromOptions;
  const explicit = trimString(options && /** @type {{ manifestPath?: string }} */ (options).manifestPath);
  const candidates = [
    explicit,
    path.join(__dirname, '..', 'plugin.manifest.json'),
    path.join(__dirname, 'plugin.manifest.json'),
  ];
  for (const file of candidates) {
    if (!file || !fs.existsSync(file)) continue;
    try {
      const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
      const id = parsed && typeof parsed.id === 'string' ? parsed.id.trim() : '';
      if (id) return id;
    } catch {
      // 清单读失败时不盖 id，网关头仍可选。
    }
  }
  return '';
}

/**
 * @param {unknown} body
 * @param {number} status
 */
function errorFromBody(body, status) {
  const record = body && typeof body === 'object' && !Array.isArray(body) ? /** @type {Record<string, unknown>} */ (body) : null;
  const nested = record && record.error && typeof record.error === 'object' ? /** @type {Record<string, unknown>} */ (record.error) : null;
  if (nested && typeof nested.message === 'string' && nested.message.trim() !== '') {
    const code = typeof nested.code === 'string' && nested.code.trim() !== '' ? nested.code : 'BAD_RESPONSE';
    return new DexModelsError(code, nested.message, status);
  }
  const code = record && typeof record.code === 'string' && record.code.trim() !== '' ? record.code : 'BAD_RESPONSE';
  const message =
    record && typeof record.error === 'string' && record.error.trim() !== ''
      ? record.error
      : `网关请求失败（${status}）`;
  return new DexModelsError(code, message, status);
}

/**
 * @param {string} filePath
 */
function mimeFromPath(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.png') return 'image/png';
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg';
  if (ext === '.webp') return 'image/webp';
  if (ext === '.gif') return 'image/gif';
  return 'application/octet-stream';
}

/**
 * @param {unknown} ctx
 * @param {Record<string, unknown> | null} [options]
 * @returns {HostModels}
 */
function bindModels(ctx, options) {
  const host = hostModels(ctx);
  if (host) return host;
  return createStandaloneModels(options || undefined);
}

/**
 * 工作台转交宿主买断确认；独立跑直接通过。正式作者不要传第二参。
 * @param {unknown} ctx
 * @param {unknown} [options]
 */
async function requireEntitlement(ctx, options) {
  const fn =
    ctx && typeof ctx === 'object'
      ? /** @type {{ requireEntitlement?: unknown }} */ (ctx).requireEntitlement
      : null;
  if (typeof fn === 'function') {
    if (arguments.length > 1) return fn(options);
    return fn();
  }
}

/**
 * @param {Record<string, unknown> | null | undefined} options
 * @returns {HostModels}
 */
function createStandaloneModels(options) {
  const env = /** @type {NodeJS.ProcessEnv} */ ((options && options.env) || process.env);
  const fetchImpl =
    /** @type {(input: string, init?: RequestInit) => Promise<Response>} */ (
      (options && options.fetch) || globalThis.fetch.bind(globalThis)
    );
  const baseUrl = String((options && options.baseUrl) || env.DEX_GATEWAY_BASE_URL || DEFAULT_BASE).replace(
    /\/+$/,
    '',
  );
  const pluginId = resolvePluginId(options);

  /**
   * @param {string} requestPath
   * @param {{ method: 'GET' | 'POST'; body?: unknown; headers?: Record<string, string> }} init
   */
  async function request(requestPath, init) {
    const key = trimString(env.DEX_BUDDY_API_KEY);
    if (!key) throw missingKey();
    /** @type {Record<string, string>} */
    const headers = {
      Accept: 'application/json',
      Authorization: `Bearer ${key}`,
      ...(pluginId ? { 'X-Plugin-Id': pluginId } : {}),
      ...(init.headers || {}),
    };
    if (init.body !== undefined) headers['Content-Type'] = 'application/json';
    const extra = init.headers && init.headers['Idempotency-Key'];
    if (extra) headers['Idempotency-Key'] = extra;
    let response;
    try {
      response = await fetchImpl(`${baseUrl}${requestPath.startsWith('/') ? requestPath : `/${requestPath}`}`, {
        method: init.method,
        headers,
        body: init.body === undefined ? undefined : JSON.stringify(init.body),
      });
    } catch (err) {
      throw new DexModelsError('NETWORK_ERROR', err instanceof Error ? err.message : '无法连接网关', 0);
    }
    let parsed = null;
    const text = await response.text();
    if (text.trim() !== '') {
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new DexModelsError('BAD_RESPONSE', '网关返回了无法解析的响应', response.status);
      }
    }
    if (!response.ok) throw errorFromBody(parsed, response.status);
    return parsed;
  }

  /**
   * @param {{ idempotencyKey?: string }} [callOptions]
   * @returns {Record<string, string>}
   */
  function extraHeaders(callOptions) {
    const key = callOptions && typeof callOptions.idempotencyKey === 'string' ? callOptions.idempotencyKey.trim() : '';
    /** @type {Record<string, string>} */
    const headers = {};
    if (key) headers['Idempotency-Key'] = key;
    return headers;
  }

  /**
   * @param {string} filePath
   * @param {{ idempotencyKey?: string }} [callOptions]
   */
  async function uploadReference(filePath, callOptions) {
    const bytes = fs.readFileSync(filePath);
    if (!bytes || bytes.length === 0) {
      throw new DexModelsError('INVALID_BODY', `参考图是空的：${filePath}`, 400);
    }
    const contentType = mimeFromPath(filePath);
    const issued = await request('/v1/files', {
      method: 'POST',
      body: { contentType, contentLength: bytes.length },
      headers: extraHeaders(callOptions),
    });
    if (!issued || typeof issued.uploadUrl !== 'string' || typeof issued.token !== 'string' || typeof issued.key !== 'string') {
      throw new DexModelsError('BAD_RESPONSE', '网关 files 凭证无效', 502);
    }
    const form = new FormData();
    form.set('token', issued.token);
    form.set('key', issued.key);
    form.set('file', new Blob([bytes], { type: contentType }), path.basename(filePath) || 'image');
    let uploaded;
    try {
      uploaded = await fetchImpl(issued.uploadUrl, { method: 'POST', body: form });
    } catch (err) {
      throw new DexModelsError('NETWORK_ERROR', err instanceof Error ? err.message : '无法上传参考图', 0);
    }
    if (!uploaded.ok) {
      throw new DexModelsError('UPSTREAM_ERROR', `参考图上传失败（${uploaded.status}）`, uploaded.status);
    }
    if (typeof issued.id !== 'string' || issued.id.trim() === '') {
      throw new DexModelsError('BAD_RESPONSE', '网关 files 凭证无效', 502);
    }
    return issued.id;
  }

  return {
    async list() {
      return request('/v1/models', { method: 'GET' });
    },
    billing: {
      /**
       * @param {unknown} body
       * @param {{ idempotencyKey?: string }} [callOptions]
       */
      quote(body, callOptions) {
        return request('/v1/billing/quote', {
          method: 'POST',
          body,
          headers: extraHeaders(callOptions),
        });
      },
    },
    chat: {
      completions: {
        /**
         * @param {unknown} body
         * @param {{ idempotencyKey?: string }} [callOptions]
         */
        create(body, callOptions) {
          return request('/v1/chat/completions', {
            method: 'POST',
            body,
            headers: extraHeaders(callOptions),
          });
        },
      },
    },
    images: {
      /**
       * @param {unknown} input
       * @param {{ idempotencyKey?: string }} [callOptions]
       */
      async generate(input, callOptions) {
        const payload = input && typeof input === 'object' ? /** @type {Record<string, unknown>} */ (input) : {};
        const model = trimString(payload.model);
        const outputPath = trimString(payload.outputPath);
        const record = payload.input && typeof payload.input === 'object'
          ? /** @type {Record<string, unknown>} */ (payload.input)
          : {};
        const prompt = trimString(record.prompt);
        if (!model) throw new DexModelsError('INVALID_BODY', '缺少 model', 400);
        if (!prompt) throw new DexModelsError('INVALID_BODY', '缺少 prompt', 400);
        if (!outputPath || !path.isAbsolute(outputPath)) {
          throw new DexModelsError('INVALID_BODY', 'outputPath 必须是绝对路径', 400);
        }
        const rawImages = record.input_images;
        /** @type {string[]} */
        const localImages = [];
        if (Array.isArray(rawImages)) {
          for (const item of rawImages) {
            if (typeof item === 'string' && item.trim() !== '') localImages.push(item.trim());
          }
        }
        /** @type {string[]} */
        const fileIds = [];
        for (let i = 0; i < localImages.length; i += 1) {
          const fileKey = callOptions && callOptions.idempotencyKey
            ? { idempotencyKey: `${callOptions.idempotencyKey}:file:${i}` }
            : callOptions;
          fileIds.push(await uploadReference(localImages[i], fileKey));
        }
        /** @type {{ model: string; prompt: string; aspect_ratio?: string; fileIds?: string[] }} */
        const generateBody = { model, prompt };
        if (trimString(record.aspect_ratio)) generateBody.aspect_ratio = trimString(record.aspect_ratio);
        if (fileIds.length > 0) generateBody.fileIds = fileIds;
        const generated = await request('/v1/images/generate', {
          method: 'POST',
          body: generateBody,
          headers: extraHeaders(callOptions),
        });
        if (!generated || typeof generated.downloadUrl !== 'string' || generated.downloadUrl.trim() === '') {
          throw new DexModelsError('BAD_RESPONSE', '网关生图结果无效', 502);
        }
        let downloaded;
        try {
          downloaded = await fetchImpl(generated.downloadUrl);
        } catch (err) {
          throw new DexModelsError('NETWORK_ERROR', err instanceof Error ? err.message : '无法下载生成图', 0);
        }
        if (!downloaded.ok) {
          throw new DexModelsError('OUTPUT_EXPIRED', `生成图下载失败（${downloaded.status}）`, downloaded.status);
        }
        const bytes = Buffer.from(await downloaded.arrayBuffer());
        if (bytes.length === 0) throw new DexModelsError('BAD_RESPONSE', '生成图是空的', 502);
        fs.mkdirSync(path.dirname(outputPath), { recursive: true });
        fs.writeFileSync(outputPath, bytes);
        return {
          status: 'succeeded',
          output: outputPath,
          model: typeof generated.model === 'string' ? generated.model : model,
        };
      },
    },
  };
}

/**
 * @param {unknown} ctx
 * @param {http.IncomingMessage} req
 * @param {http.ServerResponse} res
 * @param {unknown} body
 */
async function handleProxy(ctx, req, res, body) {
  const models = hostModels(ctx);
  if (!models) {
    res.statusCode = 401;
    res.end(JSON.stringify({ code: 'UNAUTHORIZED', error: '宿主模型不可用' }));
    return;
  }
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  let result;
  if (req.method === 'GET' && url.pathname === '/v1/models') {
    result = await models.list();
  } else if (req.method === 'POST' && url.pathname === '/v1/billing/quote') {
    result = await models.billing.quote(body);
  } else if (req.method === 'POST' && url.pathname === '/v1/chat/completions') {
    result = await models.chat.completions.create(body);
  } else if (req.method === 'POST' && url.pathname === '/images/generate') {
    result = await models.images.generate(body);
  } else {
    res.statusCode = 404;
    res.end(JSON.stringify({ code: 'BAD_RESPONSE', error: '未知路径' }));
    return;
  }
  res.statusCode = 200;
  res.setHeader('Content-Type', 'application/json');
  res.end(JSON.stringify(result));
}

/**
 * 工作台里给 Python 子进程用：指向本机代理，并删掉开发者 Key。
 * @param {unknown} ctx
 * @param {NodeJS.ProcessEnv} [baseEnv]
 */
function childEnv(ctx, baseEnv) {
  const env = { ...(baseEnv || process.env) };
  delete env.DEX_BUDDY_API_KEY;
  delete env.HTTP_PROXY;
  delete env.HTTPS_PROXY;
  delete env.ALL_PROXY;
  delete env.http_proxy;
  delete env.https_proxy;
  delete env.all_proxy;
  env.NO_PROXY = '127.0.0.1,localhost';
  env.no_proxy = '127.0.0.1,localhost';
  const host = hostModels(ctx);
  if (!host) return Promise.resolve(env);
  if (!proxyUrlPromise) {
    proxyUrlPromise = new Promise((resolve, reject) => {
      const server = http.createServer((req, res) => {
        /** @type {Buffer[]} */
        const chunks = [];
        req.on('data', (chunk) => {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
        });
        req.on('end', () => {
          let parsed = null;
          const raw = Buffer.concat(chunks).toString('utf8');
          if (raw.trim() !== '') {
            try {
              parsed = JSON.parse(raw);
            } catch {
              res.statusCode = 400;
              res.end(JSON.stringify({ code: 'INVALID_BODY', error: 'JSON 无效' }));
              return;
            }
          }
          handleProxy(ctx, req, res, parsed).catch((err) => {
            const code = err && typeof err.code === 'string' ? err.code : 'SERVER_ERROR';
            const status = err && typeof err.status === 'number' && err.status >= 400 ? err.status : 500;
            res.statusCode = status;
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ code, error: err instanceof Error ? err.message : '代理失败' }));
          });
        });
      });
      server.listen(0, '127.0.0.1', () => {
        const address = server.address();
        if (!address || typeof address === 'string') {
          reject(new Error('无法监听本机代理'));
          return;
        }
        server.unref();
        resolve(`http://127.0.0.1:${address.port}`);
      });
      server.on('error', reject);
    });
  }
  return proxyUrlPromise.then((url) => {
    env.DEX_BUDDY_MODELS_URL = url;
    return env;
  });
}

module.exports = {
  DEFAULT_BASE,
  MISSING_KEY,
  DexModelsError,
  bindModels,
  requireEntitlement,
  childEnv,
  SDK_VERSION,
};
