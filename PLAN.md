# Agnez platform agent implementation plan

Goal: One persistent conversational Agnez controls real GrowIt UI and APIs.
Architecture: Native ElevenLabs tools share a bounded frontend registry and semantic interview/change executor. GLM remains app reasoning, with exact pending approvals and no arbitrary code or backend routes.
Stack: Existing React/Vite, ElevenLabs React SDK, FastAPI/SQLite.

- [x] Design read/review and user approval. docs/superpowers/specs/2026-10-10-agnez-platform-agent-design.md.
- [x] Implement real screen/field/control registry with credential exclusion, stale IDs and effect gates.
- [x] Implement semantic native tools: interview, plan draft, propose/confirm, current task reasoning.
- [x] Replace competing Talk/SAY loop with single native Agnez conversation and receipts. Preserve dock/orb/mobile.
- [x] Patch actual provider prompt/tools, fixed chosen language, no autonomous story workflow.
- [x] Repair old immediate apply and forced motion paths.
- [x] Verify actual native tool calls, full decoded audible speech, English actual source audio and multi-turn location/repeat/navigation.
- [x] Adversarial registry/approval tests, backend638passed/1skipped, build380ms, desktop/mobile UI and console checks.
- [x] Record coverage, measured results and remaining limitations.
- [x] Replace the stale GitHub README with verified setup, provider, feature, and repository guidance plus Mermaid architecture, action, campaign, and deployment diagrams.
- [x] Write a provider-neutral deployment plan with current blockers and staging/release gates.
- [x] Commit and push the reviewed branch (`a7c7ac0`, origin/main).
- [ ] Select a host and production URL before provider-specific deployment setup.

Current evidence: native start/answer tools on actual recorded Starbucks/cafe/Bangalore Karnataka plus repeat at1440/390, one token each, no locality loop. Registry stale/secret/fresh-confirmation gates passed both widths. Long audible output raw=audible8.4907/7.8507s; Scribe confirms all nine options and final question. Backend638passed,1skipped. Native barge/control request exposed vendor Prompt Injection false-positive termination; targeted guardrail/application authorization fix and native control acceptance passed.

Final gates: denied-microphone typed native conversation navigates Memory at1440/390 with one initial denied microphone request and none in fallback, no page/console errors. Agent-page request handoff reaches Memory at both widths; mobile dock80px/desktop245px, End accessible, no overflow, screenshots inspected. Native control test already verified real data fill without save and actual voice interruption. Human microphone/audible quality and production deployment were not tested. Provider integration and paid/external effects have the explicit coverage limits in progress.md.

Final material voice-approval bridge: exact one-use click proof connects confirmed native actions to the existing browser-confirm handlers for customer removal, clearing Memory and email-to-customers. Four handler branches source checked; destructive/send operations deliberately not executed. Reversible Settings proof/replay/route regression and final registry rerun passed at both widths. Combining marks preserved and affirmative phrases closed to unqualified acknowledgements.

Final bridge evidence: approved-click.json verifies exact event acceptance, replay/copied-event/changed-route rejection and restored real service state at1440/390. Final platform-registry.json verifies credential exclusion, query and real accessible Edit labels, unprovided owner values rejected, stale/premature/qualified/duplicate confirmations rejected, owner-provided edit and fresh Hindi confirmation accepted. Build380ms and git diff --check clean. Four irreversible/send handlers remain source verified, not live executed.

README diagrams and hosting plan added on 2026-10-10. Mermaid diagrams render in GitHub Markdown. Deployment provider and production URL remain unselected. See docs/deployment-plan.md.
