-- Founder Admin P1/P2 (CONTRACTS §8): declare the new founder capabilities and their audit action names.
-- Additive only; apply after 055. Reapplication must be safe. No operator row is changed here: granting a capability
-- to the founder stays a separate reviewed enrollment step. Every write behind these capabilities also needs a fresh
-- second factor (step_up), a preview -> confirm pair and a content-free audit row; the founder agent never holds them.
begin;
alter table rafii_control.platform_operators drop constraint if exists platform_operators_capabilities_check;
alter table rafii_control.platform_operators add constraint platform_operators_capabilities_check
 check(capabilities <@ array['control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename',
  'incidents.ack','followups.write','control.settings','founder.agent.turn','founder.call.request',
  'usage.reconcile','credits.adjust','accounts.block','refunds.prepare','founder.export']::text[]);
alter table rafii_control.admin_audit_log drop constraint if exists admin_audit_log_action_check;
alter table rafii_control.admin_audit_log add constraint admin_audit_log_action_check check(action in ('session.exchange','control.read','metrics.query','customers.read','workspaces.read','engineering.read','audit.read','copilot.use','workspaces.test.rename',
 'incidents.ack','followups.write','control.settings','founder.agent.turn','founder.call.request',
 'usage.reconcile','credits.adjust','accounts.block','refunds.prepare','founder.export','prohibited'));
commit;
