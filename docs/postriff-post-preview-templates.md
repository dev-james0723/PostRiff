# PostRiff：Post preview（iPhone 手機 mockup）研究同 template 記錄

> 狀態：已落實喺 `web/`（未 commit）
> 日期：2026-09-16
> 位置：
> - **Calendar**：撳入任何一個 post，popover 右邊出 iPhone preview
> - **Queue**：「Waiting for approval」每張卡右邊直接顯示（批核前就見到）；「Publishing jobs」每行有眼睛掣，撳開睇
> - **Dev 環境**：`/dev/post-previews` 並排睇全部 template（production 係 404）
> 研究方法：6 個研究 agent 分組查 33 個 app 而家（2025–2026）嘅 iPhone 介面。來源包括開源 app code（Bluesky、Mastodon、Pixelfed、Telegram）、App Store／Google Play 截圖取色、官方 help center 同設計規格、官方網站嘅 style sheet、改版新聞。

---

## 0. 一句講完

**每個 channel 一個 template，照住嗰個 app 而家嘅真實介面畫：只有 post 本身係真，其餘係 app 外殼。**

| 真嘅（嚟自 approved manifest） | 模擬嘅（app 外殼） | 刻意唔做 |
|---|---|---|
| 內文、相片／影片（經 API 讀私人媒體）、帳號名、發佈時間（連狀態列時鐘） | top bar、tab bar、按鈕、字眼、顏色 | 假頭像相（用字母 monogram）、假讚好數（0 就隱藏，或者照 app 顯示 0 嘅方式）、估 server／域名 |

冇相但 app 一定要相（例如 Instagram、TikTok）：顯示虛線框嘅 PostRiff 提示，唔會扮係 app 一部分。每部手機下面都寫住「The app has the final say on layout」。

## 1. 檔案

| 檔案 | 做咩 |
|---|---|
| `web/src/components/application/post-preview/post-preview.tsx` | `PostPreview`：揀 channel template（lazy load）＋ caption |
| `.../use-preview-post.ts` | manifest → preview 資料；相片用 Library 同一個 React Query cache key |
| `.../phone-frame.tsx` | 393×852 iPhone 畫面、Dynamic Island、狀態列、home indicator；template 用真實 app 尺寸排版，外框整體縮細 |
| `.../parts.tsx` | 共用：monogram、連結顏色、「more」截斷、媒體、grid、tab bar、時間 |
| `.../app-icons.ts` | 畫其他 app 外殼用嘅 icon（同 PostRiff 自己嘅 icon 分開） |
| `.../templates/*.tsx` | 33 個 channel template＋`generic`；`vertical-feed.tsx` 係抖音、快手、Moj 共用嘅直向短片底層 |
| `.../gallery.tsx` ＋ `web/src/app/dev/post-previews/page.tsx` | dev 檢查頁：無相／一張相／多張相切換 |
| `.../manifest-preview.tsx` | `ManifestPreview`：頁面用呢個，畀 manifest 就得（自動用瀏覽器時區、server 上唔 render） |
| `web/src/features/calendar/calendar-view.tsx` | popover 左邊詳情、右邊 preview（手機闊度會上下排、可以捲動） |
| `web/src/features/queue/queue-view.tsx` | 審批卡：左邊詳情、右邊手機（闊過 1400px 兩張卡並排）；jobs 表格：眼睛掣開 popover，掣位固定對齊 |

## 2. 33 個平台：模擬邊個畫面、重點、把握

把握：**高**＝開源 code 或官方規格／實測；**中**＝App Store 截圖或新聞截圖；**低**＝有部分未確認（見第 4 節）。

| Channel | 模擬畫面 | 認得出嘅重點 | 把握 |
|---|---|---|---|
| Instagram | Home feed post | 頂部「+ / wordmark / 心」；Home · Reels · Messages · Search · Profile；caption 兩行「… more」 | 高 |
| Threads | For you feed | 36pt 頭像左欄、全文唔截；Home · Messages · + · Activity · Profile；Search 搬咗上頂 | 高 |
| Facebook Pages | Home feed（2025-12 改版） | ☰＋藍色 wordmark；讚／留言／分享只有 icon；六個 tab 有 label | 高 |
| X | For you timeline | 「@handle · now」、四個數＋書籤分享；Grok、Chat tab；藍色 compose 掣 | 高 |
| WhatsApp Channels | Channel 畫面 | 米色塗鴉牆紙、白色 bubble 時間喺入面、玻璃圓掣；follower 冇輸入欄 | 高 |
| LinkedIn | Home feed 卡 | 米色間隔 #EAE6DF、三行「…more」、Like · Comment · Repost · Send；active tab 頂部黑線 | 中 |
| Reddit | Home feed（iOS 26 玻璃，2026-05） | 浮動 ≡／Search Reddit／+；Vote、Comment 外框膠囊；浮動 Home · Inbox · You | 高 |
| Bluesky | Following feed | 蝴蝶 logo；左 Reply · Repost · Like、右 Bookmark · Share · …；圖片排法按數量 | 高（source code） |
| Mastodon | Following timeline（2026.07） | 圓角方形頭像、「now · @user@server」、全文 17pt；Reply · Boost · ☆ · Bookmark · … | 高（source code） |
| Pixelfed | Home feed（v1.8.0） | 「Pixelfed」字樣＋地球／信封／搜尋；「View More」、「Public · Just now」 | 高（source code） |
| Pinterest | Pin 大圖頁 | 冇 top／tab bar；紅色 Save（圓角 16）；有連結先出「Visit site」 | 中高 |
| Google Business Profile | Maps 地點頁 → Updates | Updates tab 藍綠色、By owner／By visitors；卡片冇讚好 | 中 |
| YouTube | 橫片：Home feed；直片：Shorts | Shorts 2026-06 起用心形、冇 Dislike；+ 圓掣；白色 Subscribe | 高 |
| TikTok | For You | 紅色 + 頭像、黑膠碟、青紅 + 掣；caption 兩行「more」；相片 carousel 點 | 高 |
| Snapchat | Spotlight | 頂部「Spotlight」；heart · repost · comment · share · …；Spotlight tab 紅色 | 中 |
| Moj | Home 直向片 | 白底橙色 +、「...see more」、SERIES tab | 中 |
| ShareChat | Home feed 卡（淺色） | 彩色頂邊、「文A Hindi」、WhatsApp 做第一個動作、「अभी」 | 低 |
| 小紅書 | 圖文：筆記詳情頁；影片：全黑播放器 | 36pt 頭像＋「关注」紅框、1/N pill、紅色點、18pt 標題、藍色 #話題、「说点什么...」＋点赞／收藏／评论 | 高（官方 preview 樣式）／影片中 |
| 抖音 | 首页 › 推荐 | 「精选 团购 关注 经验 推荐」＋⇌；紅 + 頭像、赞／抢首评／收藏／分享、黑膠碟；白框 + | 高（右欄、tab）／中低（零數字眼） |
| 快手 | 精选（底部 tab） | 頂部冇 tab；capsule 形 +（#FE3666）；「@昵称 创作的原声」；首页／精选／⊕／消息／我 | 中 |
| 微信視頻號 | 发现 › 视频号 › 推荐 | 「关注 · 朋友♡ · 推荐」；caption 喺名上面；赞 · 转发 · ♡ · 评论（數字喺下面）；冇底 bar | 中 |
| 微博 | 首頁「关注」feed 卡 | 日曆 icon、「关注▾ · 推荐」橙黃底線、橙色圓 +；藍色 #話題#、「...全文」；相片 grid 規則；转发／评论／赞 | 高（版面）／中（色值） |
| 哔哩哔哩 | 有片：影片頁；冇片：动态卡 | 粉紅 tab 底線、点赞／不喜欢／投币／收藏／分享、粉紅 + | 中高 |
| 知乎 | 推荐 feed 文章卡（11.0，2026-08） | 粗體標題、赞同／收藏／评论；看山 tab、藍色 + 膠囊 | 高 |
| QQ 空間 | 好友动态 说说 | 「今天HH:mm」、相片貼邊、黃色 + | 高（卡片）／低（tab） |
| 飛書 / Lark | 群聊 bot 卡片（8.0，2026-09） | 淺藍漸變 header、「机器人」標籤、群公告 tab、302px 卡 | 高（官方卡片規格） |
| Dcard | 推薦 feed 卡 | 看板頭像＋匿名徽章、「板 · 追蹤」、愛心／留言／收藏／分享、藍色 + | 高 |
| Telegram | Channel 畫面（2025-10 玻璃） | 塗鴉漸變牆紙、白 bubble、圓形分享掣、浮動 Mute | 高（source code） |
| Discord | Announcement channel（2026-08） | 擴音器頻道、#1A1A1E、方角輸入欄 | 顏色高／外殼中低 |
| LINE 官方帳號 | Talk room | 白色 header＋「自動で送信しています」、#8CABD8 背景、「メッセージを入力」 | 高 |
| KakaoTalk Channel | Channel 聊天室（26.8.0） | #ABC1D1、圓角方形頭像、相片＋文字同一張卡＋「공유하기」、冇輸入欄 | 高 |
| Naver Blog | Post 頁 | 26px 標題、「2026. 9. 16. 08:18」、綠色「+ 이웃추가」、공감／댓글 | 高（樣式）／中低（外殼） |
| note | 文章頁 | 2:1 封面、20px 粗標題、スキ、フォロー、浮動心形 | 高（排版）／中低（外殼） |

## 3. 2025–2026 年影響 template 嘅改版

- **Instagram**：tab 改做 Home · Reels · Messages · Search · Profile（2025-10 至 2026-03 陸續推出）；3:4 相（2025-05 起）；新 wordmark（2026-08 公佈）。
- **Threads**：Search 搬上頂、tab 加 Messages；Liquid Glass tab bar（2026-05/06）。
- **Facebook**：2025-12-09 改版，tab 次序 Home · Friends · Reels · Marketplace · Notifications · Profile。
- **X**：DM 變 XChat（2025-11）；Grok 取代 Communities（2026-02）；iOS 取消 Dim 主題（2026-03）。
- **Reddit**：iOS 26 Liquid Glass（2026-05），Create 搬上頂，tab 淨返 Home · Inbox · You。
- **YouTube Shorts**：心形取代讚好、Dislike 移除（2026-06 起）。
- **Snapchat**：「Subscribe」變成付費訂閱（2026-02），免費係 Follow／Add。
- **Moj**：改名「Moj: Short Drama & Reels」，加 Series tab。
- **知乎**：11.0（2026-08-07），第二個 tab 變「看山」。
- **飛書 / Lark**：8.0（2026-09）聊天頁。
- **小紅書**：影片筆記曾經試過抖音式右欄（2024-12 至 2025-01），而家官方素材係底部 bar；tab 第二格名幾次改（購物、視頻、熱門、市集）。
- **微博**：v16.7.2（2026-07）「视频」取代「超话」tab。
- **Telegram**：玻璃設計（2025-10）。**Discord**：mobile 主題同 desktop 一致（2026-08）。
- **LINE**：官方帳號 header 顏色同徽章規則（2026-04-01）。**KakaoTalk**：26.8.0 頻道訊息入「채널」資料夾。

## 4. 未確認 / 已知限制

- **平台自己會 A/B test**：tab 次序同按鈕位可能同用戶實際見到嘅唔同，所以 caption 寫明「The app has the final say」。
- **未確認**：Instagram iOS carousel 點嘅位置、Threads iOS 左上角 icon、Facebook link preview 樣式、LinkedIn「+N」相格、Pinterest 影片控制、Google 卡片 CTA 位置、Snapchat 免費 Follow 掣字眼、Moj 頂部 tab 同 Hindi 字眼、ShareChat 而家 iPhone app（App Store 截圖好舊）、Discord 手機 header 同唔可以發言時嘅底欄、LINE 未 focus 輸入欄、Naver Blog 同 note 原生外殼。
- **中國平台未確認**：抖音零讚／收藏字眼同時間行、快手精选頂部同零數字眼、視頻號「展开」同 ♡ label、微博「全文」「长图」label、小紅書影片筆記預設版面。
- **故意唔顯示**（PostRiff 冇呢啲資料）：真頭像、LinkedIn headline／關係度數、訂閱／粉絲數、Telegram 觀看次數、Kakao 頻道聯絡資料、驗證徽章、小紅書／抖音 IP 屬地、微博「来自」客戶端。
- **App 字型**（Chirp、TikTok Sans、gg sans、Pin Sans、Nunito、나눔고딕）冇 embed，用系統字替代；CJK app 按市場揀 PingFang SC／TC、Hiragino、Apple SD Gothic Neo。
- **只做淺色模式**：app 本身會跟手機深色模式，之後有需要可以加深色版本。

## 5. 主要來源（節錄）

- **開源 app code**：
  - github.com/bluesky-social/social-app
  - github.com/mastodon/mastodon-ios（tag 2026.07）
  - github.com/pixelfed/pixelfed-rn（v1.8.0）
  - github.com/TelegramMessenger/Telegram-iOS
- **官方**：
  - about.fb.com（Instagram、Facebook 改版圖）
  - LinkedIn Help、Reddit Help changelog、blog.youtube、newsroom.tiktok.com、newsroom.snap.com
  - open.feishu.cn 卡片設計規格、support.dcard.in、kakaobusiness.gitbook.io、lycorp.co.jp、help-note.com、m.blog.naver.com 樣式
- **App Store／Google Play 截圖取色**：
  - Instagram、LinkedIn、Reddit、Pinterest、Google Maps、Bilibili、知乎、QQ 空間、飛書、Dcard、Moj、ShareChat、Snapchat
- **新聞／改版報導**：
  - wabetainfo.com（WhatsApp）、piunikaweb.com（Instagram、X、Reddit）、9to5google.com（YouTube）、9to5mac.com（TikTok）
  - mydrivers.com、163.com（知乎 11.0）、androidauthority.com（YouTube 截圖）
