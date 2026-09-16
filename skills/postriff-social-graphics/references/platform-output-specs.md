# Platform output specifications

## Status and use

This registry gives planning defaults for asset production. It is not a permanent statement of platform limits. Before final export, read the current platform adapter/capability report and record the source, retrieval time, account type, native format, MIME/file-size rules, pixel/aspect constraints, duration, crop behavior, and safe-area profile actually used.

If current constraints are unavailable or contradict this registry, keep the asset as a draft and report `platform_constraints_unverified`. Do not guess.

## Planning canvas families

| Family | Planning baseline | Typical use |
|---|---:|---|
| `square-adaptive` | 1080 × 1080, 1:1 | Square feed image or community card |
| `portrait-editorial` | 1080 × 1350, 4:5 | Feed graphic and carousel |
| `portrait-note` | 1080 × 1440, 3:4 | Xiaohongshu-style cover/carousel planning |
| `landscape-social` | 1200 × 675, 16:9 | Wide feed visual and video-derived still |
| `landscape-link` | 1200 × 628, about 1.91:1 | Link/article preview planning |
| `youtube-thumbnail` | 1280 × 720, 16:9 | YouTube long-form thumbnail |
| `vertical-fullscreen` | 1080 × 1920, 9:16 | Story, Reel/Short/TikTok cover, vertical-video package |
| `vertical-pin` | 1000 × 1500, 2:3 | Pinterest standard Pin |
| `document-page` | 1080 × 1350, 4:5 | LinkedIn document/carousel planning |

These are editable production masters. The adapter owns the final accepted export dimensions and may require a different canvas.

## Safe-area model

Do not hardcode one permanent pixel safe zone per platform. Each exported asset references a versioned `safe_area_profile` with:

- canvas width and height;
- top, bottom, left, and right protected regions;
- avatar/title/control overlays;
- grid/profile crop;
- cover-frame crop;
- caption or subtitle reserve;
- device/profile/account-specific differences;
- source and `reviewed_at` time.

For 9:16 assets, keep the principal face/object and essential headline away from top/bottom controls and the right-side action rail. For thumbnails and covers, verify both the full image and the smallest common preview. Safe-area math is necessary but does not replace visual preview.

## All-channel visual routing

| Adapter | Native visual outputs to plan | Default treatment for the creator | Runtime checks |
|---|---|---|---|
| YouTube | Long-video thumbnail; Short cover/frame; Community image/GIF/video/poll/quiz visual | Thesis-led thumbnail, performance/product evidence, restrained Community visual | Exact surface, thumbnail rules, Community eligibility, cover behavior |
| Instagram | 4:5/square post; carousel; Story; Reel cover | Visual essay, real photo/UI, reflective diary, product walkthrough | Post vs carousel vs Story vs Reel, crop, alt text, account capability |
| Facebook | Image/link post; carousel where available; Story; Reel cover; event visual | Accessible context, real video/photo, event/community framing | Page identity, derivative capability, link preview and crop |
| LinkedIn | Feed image; document pages; video cover; article cover | Builder insight, decision diagram, product lesson, real evidence | Post/document/video/article surface and current upload rules |
| X | Landscape/square image; thread sequence; video cover; link card | One clear visual claim, annotated evidence, concise diagram | Media count, crop, card rendering, alt text and account limits |
| TikTok | 9:16 video package and cover | Spoken-hook cover, product/music/action frame | Valid video required, cover selection, UI safe area, sound rights |
| Threads | Image/video attachment and optional sequence | Conversational editorial visual; no forced X clone | Media/crop/alt-text capability and current account behavior |
| Xiaohongshu | Portrait cover; image-note carousel; video cover | Cover-first useful note, diary/how-to, Simplified Chinese localization | Current image-note/video ratios, title/crop, ordered media, originality |
| Douyin | 9:16 video and cover | Fast visual hook, Chinese on-screen text | Valid video, cover, subtitles, UI safe area, audio rights |
| WeChat Channels | Video cover and video-led card | Credible personal/product/music visual | Valid video, title/cover constraints, account/composer rules |
| Bilibili | Video cover; inline/supporting images | Deeper music/tech framing with strong readable cover | Cover ratio/size, title relationship, current creator rules |
| Reddit | Subreddit-permitted image, gallery, link card, or video cover | Evidence-first and community-native; often no designed asset | Exact subreddit rules, self-promotion, media type, disclosure |
| Pinterest | Vertical Pin; video Pin; board cover where relevant | Evergreen tutorial, system map, article/product discovery | Pin type, link domain, board, aspect/file limits, text legibility |
| Bluesky | Image set; external card; supported video cover | Calm microblog visual, diagram, real photo | Facets/card behavior, media limits, alt text, PDS/account rules |
| Telegram | Photo; album; video cover; poll/card visual | Concise broadcast support, not a public-feed poster | Exact destination, media group order, compression, notification policy |
| Google Business Profile | Location photo; event/offer/update image | Real studio/event/service evidence | Exact owned location, post category, image and CTA constraints |
| Discord | Attachment; embed image; forum/announcement visual | Useful community artifact, preview, changelog, event card | Exact channel/thread, embed rendering, attachment limit, mentions |
| Feishu / Lark | Image; file preview; interactive-card graphic | Clear operational update or event card | CN/global environment, card/image schema, tenant/chat rules |
| Weibo | Image set; public-feed graphic; video cover | Timely Chinese visual commentary or launch asset | Image count/ratio, topic markers, video route, account limits |
| Zhihu | Article/answer cover; inline diagram/image; video cover | Credible explanatory/editorial visual | Exact answer/article/idea surface, source disclosure, composer rules |
| Tencent QQ | Community-message image/card; Qzone image/video cover | Destination-specific community or public-feed asset | QQ community vs Qzone isolation, media type, mention/audience rules |
| Pixelfed | Photo; album; video cover | Photography, studio, performance, product visual story | Exact instance limits, alt text, sensitive flag, visibility |
| Mastodon | Image set; poll/supporting visual; video cover | Accessible diagram/photo with content-warning awareness | Exact instance version/limits, alt text, visibility, processing |
| Snapchat | Story/Saved Story/Spotlight vertical package | Immediate behind-the-scenes or music/product moment | Valid vertical video where required, profile eligibility, sound rights |
| WhatsApp Channels | Exact-channel image/video/link visual | Concise opt-in broadcast support | Channel surface, media options, audience and browser behavior |
| LINE Official Account | Image; rich/Flex message visual; video cover | Japan-facing broadcast or campaign card | Message order, quota, audience mode, template/render rules |
| note | Article cover and inline media | Japanese editorial essay, music/building story | Current composer cover/inline rules, paid/free state untouched |
| ShareChat | Native image or vertical-video package | Selected regional-language visual with human review | Language/market, current creator route, media and cultural review |
| Moj | 9:16 video and cover | India-focused music/creator short-form | Valid video, cover, subtitles, language and music rights |
| KakaoTalk Channel | Approved message-template media | Korean opt-in informational/promotional card | Kakao Business product, template review, quota, audience consent |
| Naver Blog | Article cover and inline media | Korean search-aware editorial visual | Current composer rules, category/blog identity, link/media behavior |
| Kuaishou | 9:16 video and cover | Mainland creator/music/product short-form | Valid video, cover, Chinese captions, rights and creator surface |
| Dcard | Board-permitted image/link/video cover | Native discussion support, screenshots or diagrams over ads | Exact board rules, affiliation disclosure, account and media eligibility |

## Format isolation

- A YouTube thumbnail does not qualify a YouTube Community Post image or Short package.
- A static Story design does not become a Reel, Short, TikTok, Douyin, Kuaishou, Moj, Snapchat, or WeChat Channels video.
- A TikTok route or export does not qualify Douyin, Kuaishou, or Moj.
- Instagram Story, Facebook Story, Instagram Reel, and Facebook Reel are separate native outputs even when they share a 9:16 source.
- A LinkedIn document/carousel is a sequence of document pages, not an Instagram carousel upload copied unchanged.
- Mastodon and Pixelfed constraints are instance-bound and never interchangeable by assumption.
- QQ community graphics and Qzone feed graphics belong to separate destination families.
- Community, knowledge, business-location, and opt-in broadcast assets are never created through an `all_public_feeds` wildcard.
