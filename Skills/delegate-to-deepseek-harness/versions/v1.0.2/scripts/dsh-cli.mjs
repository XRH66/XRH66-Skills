#!/usr/bin/env node
/**
 * dsh-cli - low-token local entry for driving the running DSH Web instance.
 *
 * It talks to the already-running loopback MCP endpoint (http://127.0.0.1:3080/mcp)
 * and starts no second DSH process. Authentication is read from the
 * [mcp_servers.dsh_harness] section of the Codex config; the credential is
 * sent only on the MCP transport and is never printed or written.
 *
 * Commands:
 *   start  --cwd <path> --task-file <file> [--permission <preset>]
 *   send   --session <id> --task-file <file> [--steer]
 *   status --session <id>
 *   result --session <id> --request <id> [--wait-ms 20000]
 *
 * Every successful call writes exactly one compact JSON line to stdout.
 * Failures write one compact JSON line to stderr and exit non-zero.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';

// Resolve the already-installed SDK from the local dsh-mcp-control checkout.
// This keeps the skill copy runnable from any directory without installing deps.
const require = createRequire('X:/Aiapp/dsh-mcp-control/package.json');
const { Client, StreamableHTTPClientTransport } = require('@modelcontextprotocol/client');

const MCP_URL = 'http://127.0.0.1:3080/mcp';
const CODEX_CONFIG = 'C:/Users/13179/.codex/config.toml';
const DEFAULT_PERMISSION = 'danger-full-access';
const DEFAULT_WAIT_MS = 20000;
const TOOL_TIMEOUT_MS = 45000;

const USAGE = `usage:
  dsh-cli.mjs start  --cwd <path> --task-file <file> [--permission <preset>]
  dsh-cli.mjs send   --session <id> --task-file <file> [--steer]
  dsh-cli.mjs status --session <id>
  dsh-cli.mjs result --session <id> --request <id> [--wait-ms 20000]

Task files are read as UTF-8. start uses permission preset "danger-full-access"
unless --permission names another native preset. Output is one compact JSON line.`;

/** A failure that maps to a stable error code and a non-zero exit. */
class CliError extends Error {
  constructor(code, message, exitCode = 1) {
    super(message);
    this.name = 'CliError';
    this.code = code;
    this.exitCode = exitCode;
  }
}

function usage(message) {
  return new CliError('usage', message, 2);
}

/** Minimal `--flag value` / `--flag` parser; unknown flags are refused. */
function parseArgs(argv) {
  const [command, ...rest] = argv;
  const allowed = {
    start: new Set(['cwd', 'task-file', 'permission']),
    send: new Set(['session', 'task-file', 'steer']),
    status: new Set(['session']),
    result: new Set(['session', 'request', 'wait-ms']),
  };
  if (!Object.hasOwn(allowed, command)) {
    throw usage(command === undefined ? 'missing command' : `unknown command: ${command}`);
  }
  const flags = {};
  for (let i = 0; i < rest.length; i += 1) {
    const token = rest[i];
    if (!token.startsWith('--') || token === '--') throw usage(`unexpected argument: ${token}`);
    const name = token.slice(2);
    if (!allowed[command].has(name)) throw usage(`unknown flag for ${command}: --${name}`);
    if (name === 'steer') {
      flags.steer = true;
      continue;
    }
    const value = rest[i + 1];
    if (value === undefined || value.startsWith('--')) throw usage(`missing value for --${name}`);
    flags[name] = value;
    i += 1;
  }
  return { command, flags };
}

function requireFlag(flags, name) {
  const value = flags[name];
  if (typeof value !== 'string' || value.length === 0) throw usage(`missing --${name}`);
  return value;
}

/** Read only [mcp_servers.dsh_harness] from the Codex config; never echo it. */
function readDshHarnessAuthorization() {
  let text;
  try {
    text = fs.readFileSync(CODEX_CONFIG, 'utf8');
  } catch {
    throw new CliError('config', `cannot read Codex config: ${CODEX_CONFIG}`);
  }
  const header = /^[ \t]*\[mcp_servers\.dsh_harness\][ \t]*(?:#.*)?$/m.exec(text);
  if (header === null) {
    throw new CliError('config', `no [mcp_servers.dsh_harness] section in ${CODEX_CONFIG}`);
  }
  const rest = text.slice(header.index + header[0].length);
  const nextSection = rest.search(/^[ \t]*\[/m);
  const section = nextSection === -1 ? rest : rest.slice(0, nextSection);
  const table = /^[ \t]*http_headers[ \t]*=[ \t]*\{([\s\S]*?)\}/m.exec(section);
  if (table === null) {
    throw new CliError('config', 'dsh_harness has no http_headers inline table');
  }
  const auth = /(?:^|[,{\s])Authorization[ \t]*=[ \t]*("(?:[^"\\]|\\.)*"|'[^']*')/m.exec(table[1]);
  if (auth === null) {
    throw new CliError('config', 'dsh_harness http_headers has no Authorization header');
  }
  let value;
  try {
    value = auth[1].startsWith('"') ? JSON.parse(auth[1]) : auth[1].slice(1, -1);
  } catch {
    throw new CliError('config', 'dsh_harness Authorization header is not a valid string');
  }
  if (!/^Bearer\s+\S+$/.test(value)) {
    throw new CliError('config', 'dsh_harness Authorization is not a Bearer credential');
  }
  return value;
}

/** Resolve cwd to a fully qualified existing directory (endpoint requires it). */
function resolveCwd(input) {
  const absolute = path.resolve(input);
  let stat;
  try {
    stat = fs.statSync(absolute);
  } catch {
    throw new CliError('cwd', `cwd does not exist: ${absolute}`);
  }
  if (!stat.isDirectory()) throw new CliError('cwd', `cwd is not a directory: ${absolute}`);
  return absolute;
}

/** Read a UTF-8 task file, drop a BOM, and refuse an empty prompt. */
function readTaskFile(input) {
  const absolute = path.resolve(input);
  let text;
  try {
    text = fs.readFileSync(absolute, 'utf8');
  } catch {
    throw new CliError('task-file', `cannot read task file: ${absolute}`);
  }
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  if (text.trim().length === 0) throw new CliError('task-file', `task file is empty: ${absolute}`);
  return text;
}

/** Read a positive integer flag, or a zero that means "do not wait". */
function readWaitMs(value) {
  if (value === undefined) return DEFAULT_WAIT_MS;
  if (!/^\d+$/.test(value)) throw usage('--wait-ms must be a non-negative integer');
  return Number(value);
}

function excerpt(value, max = 400) {
  return value.length <= max ? value : `${value.slice(0, max)}...`;
}

function errorMessage(error) {
  if (error instanceof Error) return excerpt(error.message);
  return excerpt(String(error));
}

/** Open one MCP connection to the running Web listener. */
async function openClient(authorization) {
  const client = new Client({ name: 'dsh-cli', version: '1.0.0' });
  const transport = new StreamableHTTPClientTransport(new URL(MCP_URL), {
    requestInit: { headers: { Authorization: authorization } },
  });
  try {
    await client.connect(transport);
  } catch (error) {
    try {
      await client.close();
    } catch {
      // The connect failure is the one worth reporting.
    }
    throw new CliError('connect', `cannot reach ${MCP_URL}: ${errorMessage(error)}`);
  }
  return client;
}

function textPayload(result) {
  const part = Array.isArray(result.content)
    ? result.content.find((item) => item?.type === 'text' && typeof item.text === 'string')
    : undefined;
  if (part === undefined) return null;
  try {
    return JSON.parse(part.text);
  } catch {
    return null;
  }
}

/** Call one native tool and return its structured payload. */
async function callTool(client, name, args) {
  let result;
  try {
    result = await client.callTool({ name, arguments: args }, { timeout: TOOL_TIMEOUT_MS });
  } catch (error) {
    throw new CliError('transport', `${name} call failed: ${errorMessage(error)}`);
  }
  const payload = result.structuredContent ?? textPayload(result);
  if (result.isError === true) {
    const failure = payload?.error;
    throw new CliError(
      typeof failure?.code === 'string' ? failure.code : 'tool-error',
      typeof failure?.message === 'string' ? failure.message : `${name} failed`,
    );
  }
  if (payload === null || typeof payload !== 'object') {
    throw new CliError('protocol', `${name} returned no structured result`);
  }
  return payload;
}

async function runCommand(client, command, flags) {
  if (command === 'start') {
    const cwd = resolveCwd(requireFlag(flags, 'cwd'));
    const prompt = readTaskFile(requireFlag(flags, 'task-file'));
    const requestId = randomUUID();
    const receipt = await callTool(client, 'session_start', {
      cwd,
      prompt,
      permission_preset: flags.permission ?? DEFAULT_PERMISSION,
      request_id: requestId,
    });
    return { session_id: receipt.session_id, request_id: receipt.request_id ?? requestId };
  }

  if (command === 'send') {
    const sessionId = requireFlag(flags, 'session');
    const message = readTaskFile(requireFlag(flags, 'task-file'));
    const receipt = await callTool(client, 'session_send', {
      session_id: sessionId,
      message,
      delivery: flags.steer === true ? 'steer' : 'queue',
      request_id: randomUUID(),
    });
    return { session_id: receipt.session_id ?? sessionId, request_id: receipt.request_id };
  }

  if (command === 'status') {
    const sessionId = requireFlag(flags, 'session');
    const status = await callTool(client, 'session_status', {
      address: { kind: 'session', session_id: sessionId },
    });
    const turn = status.turn === null || status.turn === undefined
      ? null
      : { turn: status.turn.turn, open: status.turn.open, reason: status.turn.reason ?? null };
    return {
      session_id: status.session_id ?? sessionId,
      agent_status: status.agent_status,
      head_seq: status.head_seq,
      turn,
      queue_count: (status.queue?.length ?? 0) + (status.queue_omitted ?? 0),
      pending_approvals_count:
        (status.pending_approvals?.length ?? 0) + (status.pending_approvals_omitted ?? 0),
    };
  }

  const sessionId = requireFlag(flags, 'session');
  const requestId = requireFlag(flags, 'request');
  const waitMs = readWaitMs(flags['wait-ms']);
  const result = await callTool(client, 'turn_result', {
    address: { kind: 'session', session_id: sessionId },
    request_id: requestId,
    wait_ms: waitMs,
  });
  const compact = {
    state: result.state,
    reason: result.reason ?? null,
    final_message: result.final_message ?? null,
    diagnostics: result.diagnostics ?? [],
  };
  if (result.final_message_truncated === true) compact.final_message_truncated = true;
  if (typeof result.diagnostics_omitted === 'number') {
    compact.diagnostics_omitted = result.diagnostics_omitted;
  }
  return compact;
}

async function main(argv) {
  try {
    const { command, flags } = parseArgs(argv);
    // Validate local inputs before touching the credential or the network.
    if (command === 'start') {
      resolveCwd(requireFlag(flags, 'cwd'));
      readTaskFile(requireFlag(flags, 'task-file'));
    } else if (command === 'send') {
      requireFlag(flags, 'session');
      readTaskFile(requireFlag(flags, 'task-file'));
    } else if (command === 'status') {
      requireFlag(flags, 'session');
    } else {
      requireFlag(flags, 'session');
      requireFlag(flags, 'request');
      readWaitMs(flags['wait-ms']);
    }

    const authorization = readDshHarnessAuthorization();
    const client = await openClient(authorization);
    try {
      const output = await runCommand(client, command, flags);
      process.stdout.write(`${JSON.stringify(output)}\n`);
      return 0;
    } finally {
      // Every command, including a failed tool call, closes its MCP session.
      try {
        await client.close();
      } catch {
        // A close failure must not turn a delivered result into an error.
      }
    }
  } catch (error) {
    const code = error instanceof CliError ? error.code : 'internal';
    const message = errorMessage(error);
    process.stderr.write(`${JSON.stringify({ error: { code, message } })}\n`);
    if (error instanceof CliError && error.exitCode === 2) process.stderr.write(`${USAGE}\n`);
    return error instanceof CliError ? error.exitCode : 1;
  }
}

process.exitCode = await main(process.argv.slice(2));
