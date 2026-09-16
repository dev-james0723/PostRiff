# RedNote route-test approval request

**State:** pending exact user approval  
**Manifest hash:** `sha256:67d329f7b409ee6c40444bb9128bf65bef72727b75051932fef678be4f87b65a`  
**Account:** 小红薯6AA7E810 · RedNote ID 94556602041  
**Destination:** RedNote main profile through Creator Center  
**Audience for every test:** `仅自己可见` (self only)  
**Derivatives:** none  
**Deletion/cancellation:** not included

## 1. Image note — publish after approval

- Title: `Studio 圖文測試`
- Copy: `這是 James Au Studio 的私人連接測試，用於驗證圖文上傳與發佈流程。`
- Tag: `連接測試`
- Media: `rednote-image-route-test.png` · `sha256:9288420a9a08d5aaff5b777fcbe1846f07f13f8aa23d8f808849fc9ef024fd47`
- Timing: immediately after approval
- Verification: matching Creator Center note-management record
- Idempotency: `sha256:3bcb01e314706a27f76acafc0db459a33f2984970cb1e816e98ebf74ecdc08c0`

## 2. Video note — publish after image verification

- Title: `Studio 影片測試`
- Copy: `這是 James Au Studio 的私人影片連接測試，用於驗證影片上傳與發佈流程。`
- Tag: `連接測試`
- Media: `rednote-video-route-test.mp4` · 1080×1920 · 4 seconds · `sha256:c0522148bd61263faa5f9a2ecf87be754eae60b6c04b6a47486a57d339004781`
- Timing: only after the image note independently verifies
- Verification: matching Creator Center record plus playable video
- Idempotency: `sha256:f8244e6ab9e08026a4aee5c4fc21d252556e69e7c391916596c1f223c0ef796e`

## 3. Scheduled image note — submit after both immediate tests verify

- Title: `Studio 排程測試`
- Copy: `這是 James Au Studio 的私人排程測試，預定於 2026 年 9 月 15 日 10:30（美東時間）發佈。`
- Tag: `連接測試`
- Media: `rednote-schedule-route-test.png` · `sha256:61082eb2132a25b39b9b0b2b59ba59be69d97958e580d25bcabf0552c23ce5e7`
- Scheduled time: **2026-09-15 10:30 EDT** (`America/Indiana/Indianapolis`)
- Verification: matching Creator Center scheduled-note record
- Idempotency: `sha256:9f9256cfdac555906fc39110d21d61f20c61c3290cdea93778f2bec5b8c9b5cd`

Approval of this exact manifest authorizes only these three self-only route-test submissions in dependency order. It does not authorize public visibility, derivatives, edits, deletion, cancellation, comments, replies, likes, follows, products, ads, or recurring automation.
