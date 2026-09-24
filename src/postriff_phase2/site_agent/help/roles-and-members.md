---
documentId: help_roles_members
sourceType: product_help
title: Roles, members and the audit log
summary: Who can do what, invitations, and the content-free audit log.
routeFamilies: [workspace]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: roles-members
keywords: [roles, permissions, members, invite, owner, admin, editor, approver, viewer, audit, 角色, 權限, 成員, 邀請, 審計, 擁有者]
---
# Roles, members and the audit log

## Five roles

- Owner: everything, including billing, deleting the workspace, activating automations and owner-only settings such as cloud memory.
- Admin: manages members, roles and connections.
- Editor: writes and edits drafts, sources and automations.
- Approver: prepares reviews, approves posts and cancels jobs.
- Viewer: read-only.

## Grants

A grant adds one right (approve, reply, moderate, manage connections) to a member without changing their role. A viewer stays read-only whatever grants they carry. Only the owner or an admin can change access, nobody can change their own, and a grant can only be handed out by someone who holds it.

## Invitations

Invite people on [Members](/app/workspace/members). Links work once and expire after 7 days. Inviting, changing someone's access and removing a member only work shortly after a fresh sign-in.

## Audit log

The [Audit log](/app/workspace/audit) records people joining, leaving and changing roles, ownership transfers, invitations, channel connections, data exports, the cloud memory and web research choices, billing checkouts and approved replies. Events carry ids, kinds, counts and times, never post text, prompts, access tokens or email addresses. Owners and admins can read it.
