// Runs the actions the reasoning model (POST /agent/orchestrate) returns, using the app's own calls.
// The model proposes; every call here still stops at the owner's own gate (the plan lock, the change confirmation, the asset).
// Each action is attempted in order; one failure is reported and the rest still run.
import { navigate } from "../../lib/router";
import { approvePlan, generate, proposeChange, applyChange, makeVideo } from "./api";

export type OrchestrateAction = { type: string; params?: Record<string, unknown> };
export type ActionResult = { type: string; ok: boolean; detail: string };

// The reason each failure happened, in the owner's words where the server gave one.
const why = (e: unknown) => (e instanceof Error ? e.message : "failed");

export async function runActions(
  actions: OrchestrateAction[],
  ctx: { campaign_id?: string } = {},
): Promise<ActionResult[]> {
  const results: ActionResult[] = [];
  const need = () => {
    if (!ctx.campaign_id) throw new Error("no campaign is open");
    return ctx.campaign_id;
  };
  const attempt = async (type: string, fn: () => string | Promise<string>) => {
    try {
      results.push({ type, ok: true, detail: await fn() });
    } catch (e) {
      results.push({ type, ok: false, detail: why(e) });
    }
  };

  for (const action of actions || []) {
    const p = action.params || {};
    switch (action.type) {
      case "navigate":
        await attempt("navigate", () => {
          const screen = String(p.screen || "").trim();
          if (!screen) throw new Error("no screen");
          navigate(screen);
          return `opened ${screen}`;
        });
        break;
      case "set_offer_facts":
        // The frontend has no caller for PUT /campaigns/{id}/facts, so send the owner to Talk to say the offer
        // instead of inventing a save path. See docs/agent-and-voice.md.
        await attempt("set_offer_facts", () => {
          navigate("voice");
          return "opened Talk to say the offer";
        });
        break;
      case "start_plan":
        await attempt("start_plan", async () => {
          await approvePlan(need());
          return "plan locked";
        });
        break;
      case "generate_campaign":
        await attempt("generate_campaign", async () => {
          await generate(need());
          return "Campaign 0 written";
        });
        break;
      case "apply_change":
        await attempt("apply_change", async () => {
          const text = String(p.text || "").trim();
          if (!text) throw new Error("no change text");
          const proposal = await proposeChange(need(), text);
          if (!proposal.grounded) throw new Error(proposal.summary || "the change is not grounded in your facts");
          await applyChange(need(), proposal.proposal_id);
          return "change applied";
        });
        break;
      case "generate_video":
        await attempt("generate_video", async () => {
          const assetId = String(p.asset_id || "").trim();
          if (!assetId) throw new Error("no asset id");
          await makeVideo(assetId, p.aspect === "9:16" ? "9:16" : "16:9");
          return "video queued";
        });
        break;
      default:
        await attempt(action.type, () => {
          throw new Error("unknown action");
        });
    }
  }
  return results;
}
