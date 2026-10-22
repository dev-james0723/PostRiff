# P-03 Discord connect guide (draft for approval; not in the product)

Status: draft text for a help page or the connect sheet's "learn more" link. It is not wired into the release candidate, because adding it would move the frozen head. It describes only what the code does (`P-01-privacy-terms-diff.md` lists the evidence for each claim). Discord's menu names change from time to time; check the two Discord paths before publishing. The refusal, busy and late-post messages are already in the candidate (`web/src/lib/channels/discord-copy.json`, three languages).

## English

**Connect Discord to Rafii**

1. **What you need.** A Discord server where you can manage the server (owner, Administrator or the Manage Server permission). Rafii only shows servers where you have that.
2. **Two steps, two Discord screens.** First you link your Discord profile; Rafii learns your Discord user and the list of servers you belong to so you can pick one. Then you add Rafii's bot to that server.
3. **What the bot can do.** It can see the channels you choose and post there. It never pings @everyone, @here, roles or people. Rafii posts only the exact text and image you approved for that post, then reads that one message back to confirm it arrived. It does not read other messages, does not send direct messages and does not use message-content access.
4. **Permissions the bot asks for.** View Channel, Send Messages, Attach Files and Read Message History (the last one is only used to read back the message it posted).
5. **Choose where to post.** Authorize each channel separately. If Rafii cannot see a channel, give the bot access to it in Discord, or pick another.
6. **If connecting says Discord is not open for your workspace yet, or has no room,** nothing was connected and nothing was posted. Connections you already have keep working. Try again later.
7. **Remove Rafii.** Disconnecting in Rafii deletes Rafii's stored copy of your Discord tokens and stops Rafii using the connection. It does not remove the bot from your server and does not revoke the authorization at Discord. To end access on Discord's side: in Discord open User Settings, Authorized Apps, and remove Rafii; and in your server remove the bot (Server Settings, Integrations, or remove the bot from the member list).
8. **Scheduled posts.** Rafii sends a scheduled post from its own queue at the time you set. When many posts are due in the same minute, Discord posts can arrive several minutes late.

## 繁體中文

**將 Discord 連接到 Rafii**

1. **你需要甚麼。** 一個你可以管理的 Discord 伺服器（擁有者、管理員，或具有「管理伺服器」權限）。Rafii 只會列出你有此權限的伺服器。
2. **兩個步驟，兩個 Discord 畫面。** 先連結你的 Discord 個人檔案，讓 Rafii 取得你的 Discord 用戶及所屬伺服器清單，方便你揀選其中一個；然後把 Rafii 的機械人加入該伺服器。
3. **機械人能做甚麼。** 它只能看到你選定的頻道並在其中發佈內容，絕不會標記 @everyone、@here、身分組或任何人。Rafii 只會發佈你已批准的確切文字和圖片，發佈後會讀回該則訊息以確認送達。它不會閱讀其他訊息、不會傳送私訊，亦不會使用訊息內容存取權限。
4. **機械人要求的權限。** 檢視頻道、傳送訊息、附加檔案、閱讀訊息記錄（最後一項只用於讀回它自己發佈的訊息）。
5. **選擇發佈位置。** 每個頻道須分別授權。如 Rafii 看不到某個頻道，請在 Discord 內讓機械人存取該頻道，或另選頻道。
6. **如果連接時顯示 Discord 尚未向你的工作區開放，或已沒有空位，** 即代表沒有連接任何內容，也沒有發佈任何訊息。你原有的連接不受影響。請稍後再試。
7. **移除 Rafii。** 在 Rafii 中中斷連接，會刪除 Rafii 所儲存的你的 Discord 權杖，並停止使用該連接；但不會把機械人移出你的伺服器，也不會在 Discord 撤銷授權。如要在 Discord 一方終止存取：到 Discord「使用者設定」的「已授權的應用程式」移除 Rafii，並在你的伺服器移除該機械人（伺服器設定的「整合」，或從成員清單移除機械人）。
8. **排程發佈。** Rafii 會在你設定的時間，由自己的佇列發出排程訊息。如同一分鐘內有大量訊息到期，Discord 訊息可能會延遲數分鐘送達。

## 简体中文

**将 Discord 连接到 Rafii**

1. **你需要什么。** 一个你可以管理的 Discord 服务器（所有者、管理员，或具有“管理服务器”权限）。Rafii 只会列出你有此权限的服务器。
2. **两个步骤，两个 Discord 页面。** 先关联你的 Discord 个人资料，让 Rafii 获取你的 Discord 用户及所属服务器列表，方便你选择其中一个；然后把 Rafii 的机器人添加到该服务器。
3. **机器人能做什么。** 它只能看到你选定的频道并在其中发布内容，绝不会提及 @everyone、@here、身份组或任何人。Rafii 只会发布你已批准的确切文字和图片，发布后会读回该条消息以确认送达。它不会读取其他消息、不会发送私信，也不会使用消息内容访问权限。
4. **机器人请求的权限。** 查看频道、发送消息、附加文件、读取消息历史（最后一项只用于读回它自己发布的消息）。
5. **选择发布位置。** 每个频道需分别授权。如果 Rafii 看不到某个频道，请在 Discord 中让机器人访问该频道，或另选频道。
6. **如果连接时提示 Discord 尚未向你的工作区开放，或已没有名额，** 表示没有连接任何内容，也没有发布任何消息。你原有的连接不受影响。请稍后再试。
7. **移除 Rafii。** 在 Rafii 中断开连接，会删除 Rafii 所存储的你的 Discord 令牌，并停止使用该连接；但不会把机器人移出你的服务器，也不会在 Discord 撤销授权。如要在 Discord 一侧终止访问：到 Discord“用户设置”的“已授权的应用”移除 Rafii，并在你的服务器移除该机器人（服务器设置的“集成”，或从成员列表移除机器人）。
8. **定时发布。** Rafii 会在你设定的时间，从自己的队列发出定时消息。如果同一分钟内有大量消息到期，Discord 消息可能会延迟数分钟送达。

## Before publishing

- Check the two Discord paths in item 7 against Discord's current menus.
- The wording must match what the product shows on the day (the "publishing opens after testing" text in `web/src/config/channels.ts` is still unchanged).
- Terms placeholders and the privacy mailbox are open items in `P-01-privacy-terms-diff.md`.
