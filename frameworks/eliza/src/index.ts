/**
 * Token Verdict plugin for ElizaOS.
 *
 * One action — TOKEN_VERDICT — screens a token contract before the
 * agent buys, swaps, or routes funds into it ($0.02 over x402 on
 * Base, settled through the caller's payer). Payment is a seam: the
 * caller injects `pay(url, body)`, which is where x402-guard plugs
 * in (@quincygb/x402-guard's GuardedClient enforces Settled
 * pre-flight, Recheck drift checks, and a spend cap BEFORE signing).
 * A Fleet Pass can fund the guard's drift checks — see the loop-kits
 * README. With no payer configured, the action returns the unpaid
 * 402 challenge as data so the agent can decide whether to pay.
 */
/**
 * Structural mirrors of the @elizaos/core 1.x Action / Plugin shapes.
 * Declared locally on purpose: @elizaos/core 1.7.2's published type
 * entry does not reliably re-export these names to downstream
 * typecheckers (verified 2026-10-26: TS2305 on Action, IAgentRuntime,
 * Memory, Plugin, State against a clean install), while the runtime
 * contract is the object shape below — which is what the runtime
 * actually consumes.
 */
export interface ElizaMemory {
  content?: { text?: string };
}
export interface ElizaAction {
  name: string;
  similes: string[];
  description: string;
  examples: unknown[];
  validate: (runtime: unknown, message: ElizaMemory) => Promise<boolean>;
  handler: (
    runtime: unknown,
    message: ElizaMemory,
    state?: unknown,
    options?: unknown,
    callback?: (content: { text: string; action: string }) => Promise<unknown>,
  ) => Promise<boolean>;
}
export interface ElizaPlugin {
  name: string;
  description: string;
  actions: ElizaAction[];
}

export const TOKEN_VERDICT_URL =
  "https://token-verdict-production.up.railway.app/v1/verdict";

export type PayFn = (url: string, body: unknown) => Promise<unknown>;

export function decodeChallenge(headers: Headers, bodyText: string): unknown | null {
  const raw = headers.get("payment-required");
  if (raw) {
    try {
      const data = JSON.parse(atob(raw));
      if (data && Array.isArray(data.accepts)) return data;
    } catch {
      /* fall through to the body form */
    }
  }
  try {
    const data = JSON.parse(bodyText);
    if (data && Array.isArray(data.accepts)) return data;
  } catch {
    /* not a challenge */
  }
  return null;
}

export async function getTokenVerdict(
  address: string,
  chain = "base",
  pay?: PayFn,
  fetchFn: typeof fetch = fetch,
  url: string = TOKEN_VERDICT_URL,
): Promise<unknown> {
  const body = { address, chain };
  if (pay) return pay(url, body);
  const response = await fetchFn(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 200) return response.json();
  if (response.status === 402) {
    const challenge = decodeChallenge(response.headers, await response.text());
    if (challenge) return { payment_required: challenge };
  }
  return {
    error: `token verdict returned HTTP ${response.status}`,
    detail: (await response.text()).slice(0, 300),
  };
}

const ADDRESS_RE = /0x[0-9a-fA-F]{40}/;

export function makeTokenVerdictAction(pay?: PayFn): ElizaAction {
  return {
    name: "TOKEN_VERDICT",
    similes: ["SCREEN_TOKEN", "CHECK_TOKEN_RISK", "TOKEN_RISK"],
    description:
      "Screen a token contract address for risk before buying or routing funds: " +
      "returns SOLID / CAUTION / DANGER with a 0-100 score. Costs $0.02 over x402 (Base USDC).",
    examples: [
      [
        { name: "{{user1}}", content: { text: "Screen 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 before I buy it" } },
        { name: "{{agent}}", content: { text: "Screening it now.", action: "TOKEN_VERDICT" } },
      ],
    ],
    validate: async (_runtime: unknown, message: ElizaMemory) => {
      const text = message.content?.text ?? "";
      return ADDRESS_RE.test(text);
    },
    handler: async (runtime, message, _state, _options, callback) => {
      const text = message.content?.text ?? "";
      const match = text.match(ADDRESS_RE);
      if (!match) return false;
      const result = await getTokenVerdict(match[0], "base", pay);
      if (callback) {
        await callback({
          text: `Token Verdict for ${match[0]}: ${JSON.stringify(result).slice(0, 900)}`,
          action: "TOKEN_VERDICT",
        });
      }
      return true;
    },
  };
}

export function createTokenVerdictPlugin(pay?: PayFn): ElizaPlugin {
  return {
    name: "token-verdict",
    description: "Token Verdict risk screens ($0.02 over x402) for ElizaOS agents.",
    actions: [makeTokenVerdictAction(pay)],
  };
}

export default createTokenVerdictPlugin;
