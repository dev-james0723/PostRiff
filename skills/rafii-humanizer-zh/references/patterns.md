# Chinese pattern catalogue

Detector ids refer to `src/postriff_phase2/coworker/humanizer_patterns.json`.
Examples are for teaching and are mostly in zh-Hans. The same rules apply to
zh-Hant and yue. The output always follows the target locale. An "after" (改写后)
uses only information in the "before" (改写前). "Keep" (保留) marks a case that
must not be changed. Judge the patterns in clusters; one hit is rarely a reason
to edit.

## A. 铺垫代替陈述 (build-up instead of statement)

**zh.fake_contrast (翻案腔).** This sets up a misunderstanding the reader never
had, then knocks it down: 不是…而是, 并非…而是, 与其说…不如说, 看似…实则. Other
wordings of the same move count too.
- Before: 这不仅是一个导出按钮，更是通往高效工作的全新入口。它可以导出 CSV。
  After: 这个按钮可以导出 CSV。
- Keep: 错误发生在保存阶段，而不是上传阶段。(This corrects a real
  misunderstanding.) Also keep quoted speech: 作者寫道：「這不是工具，而是一面鏡子。」
- Keep: yue.not_only_more (唔單止…仲係…) is the Cantonese form. Handle it the
  same way.

**zh.you_think_actually, zh.blunt_opener.** 你以为…其实…, 说白了, 说穿了,
先说结论, 划重点. Delete the opener and state the judgement directly.

**zh.runway_signpost, yue.lets_together.** 让我们深入看看, 以下是你需要知道的,
等我哋一齊深入了解. Delete the preview. Do not fill the gap with new knowledge.
- Keep: 说实话，我还没想好。(This is a real stance.)

**zh.strawman_defense.** 不要误会，我并不是在制造焦虑。我想说的是，删除前需要确认备份。
becomes 删除前需要确认备份。Keep real objections, limits and alternatives.

**zh.reveal_colon.** This is a prompt word followed by a colon (一句话总结：,
核心是：, 关键在于：). Delete the prompt when it carries no information. When the
first half links back to earlier text, only change the colon. Keep colons that
introduce direct speech, list items and URLs.

## B. 公式化节奏 (formulaic rhythm)

**zh.hedge_stack.** 这项调整也许可能会减少读取时间，目前尚未验证。 becomes
这项调整可能减少读取时间，目前尚未验证。 Keep one hedge of the same strength.
Evidence limits (尚未验证) and legal caveats stay.

**zh.dash_reveal.** 结果终于出现了——答案揭晓了——文件无法导出。 becomes
结果是文件无法导出。
- Keep: 我们只改了标题——正文和附件都没动。(An explanatory dash, or a dash in the
  owner's voice.)

**zh.dunhao_dense, zh.four_char_parallel.** Check each item. If it carries its
own information, it stays.
- Before: 这次更新带来了创新、突破和全新的可能。它新增导出、搜索和批量重命名。
  After: 这次更新新增导出、搜索和批量重命名。
- 该方案稳定可靠、快速响应、易于维护。 may become 这套方案运行稳定、响应快，也方便维护。
  Never add metrics.
- Keep: 数量不变、顺序不变、权限不变 (three separate constraints), and lists
  that are legally or technically required.

**zh.coined_compound.** 我们采用“文稿-校对-发布一体化”机制，也就是在同一个页面完成写稿、校对和发布。
becomes 我们在同一个页面完成写稿、校对和发布。
- Keep: established terms (端到端加密) and approved brand terms.

**Adjacent sentences with the same shape (no regex).** When several sentences
in a row share one skeleton, restructure one of them. Never cut information.
Keep intended parallelism and step lists.

## C. 拔高与借权威 (inflation and borrowed authority)

**zh.ai_vocab.** 赋能, 至关重要, 深入探讨, 无缝, 抓手, 底层逻辑, 全方位. Edit these
only when they are empty or imprecise in context.
- 本文将深入探讨一个至关重要的问题：导出失败后如何重试。 becomes
  本文讨论导出失败后如何重试。
- Keep: 控制器使用闭环反馈调整输出。(A technical term.)

**zh.significance.** 团队在周三开放了文件导出，标志着协作新时代的到来。离线编辑仍在开发。
becomes 团队在周三开放了文件导出。离线编辑仍在开发。 Keep the real plan and its
status.

**zh.tail_praise.** 页面提供全文搜索，彰显了团队对创新的不懈追求。 becomes
页面提供全文搜索。
- Keep: 页面提供全文搜索，方便读者查找原文中的术语。(This gives a real purpose.)

**zh.promo.** 这家咖啡馆位于杭州市中心，装修有特色，堪称咖啡爱好者的梦想天堂。
becomes 这家咖啡馆位于杭州市中心，装修有特色。 A subjective view (我觉得很漂亮)
stays a view, not a ranking.

**zh.vague_authority.** 一些未具名的专家认为，这一设计可能减少误操作，充分体现了其重大价值。
becomes 一些未具名的专家认为，这一设计可能减少误操作。 Never invent the expert, the
institution or a date. Ask for a source in the note.

**zh.vague_association.** 他与该协会有着密切联系，具体来说，他负责协会的票务。
becomes 他负责该协会的票务。
- Keep: 他与该协会有关联，具体角色尚不清楚。(Do not guess the role.)

**zh.copula_avoid.** 这个空间作为展览场地，设有四个独立展区，总面积超过 3000 平方英尺。
becomes 这个空间是展览场地，有四个独立展区，总面积超过 3000 平方英尺。 超过 stays
超过. 可以提供 does not mean 已提供.

**zh.personified_tool.** 像一位永不疲倦的导师 becomes a statement of what the
tool actually does. Keep ordinary metaphors and concrete people used as
metaphors (像一个老师傅).

**Generalisation that covers up data already given (no regex).** 显著提升 or
大幅增长 is used even though the paragraph already gives 72%. Move the existing
figure into place. Never invent one.

## D. 公式化排版 (formulaic layout)

**zh.emoji_heading, zh.bold_decor.** Remove the decoration when it gets in the
way of reading. Keep the emoji habits the voice approves, emphasis in warnings,
and every list item. 🚀 发布安排：产品计划在第三季度发布。 becomes
发布安排：产品计划在第三季度发布。 A plan stays a plan.

**zh.ordinal_headings.** Numbering every heading with 一、二、三 across the whole
document: remove the numbers and keep the heading text. Keep 首先/其次 in the
body, ordered lists, and numbering that is referred to elsewhere ("见第三条").

**zh.list_intro_colon.** A line that only announces a list (主要有以下几点：).
Make the line say something, or join the list to the previous sentence. Never
delete list items.

**zh.straight_quotes.** Use the target locale's quotes: “” for zh-Hans, and
usually 「」 for zh-Hant and HK, unless VOICE.md says otherwise. JSON, code and
original quotes keep their form.

## E. 聊天与草稿残留 (chat and draft residue)

**zh.chatbot_residue, yue.hope_helps.** 好问题！这是导出功能的说明。它支持 CSV。希望这对您有帮助！
becomes 导出功能支持 CSV。 Keep the greeting, thanks and sign-off in a real email
or customer reply. 以下是润色后的版本 and 以下係修改咗嘅版本 must never reach the copy.

**zh.cutoff_disclaimer.** 现有材料没有记载公司的成立日期。关于这一点，可用信息确实比较有限。
becomes 现有材料没有记载公司的成立日期。 A guess stays a guess (我猜是九十年代，但没有证据).
A date that scopes the data (截至 2026年9月) stays.

**zh.restate_heading.** 本节介绍导出限制。下面说明导出限制。单个文件最大为 10 MB。
becomes 本节介绍导出限制。单个文件最大为 10 MB。

**zh.draft_talk.** 这一段是刚补充的说明，内容是文件最大为 10 MB。 becomes
文件最大为 10 MB。
- Keep: changelogs and release notes (新版本把上限从 5 MB 调整为 10 MB).

## F. 中文表达的补充检查 (Chinese-specific checks)

**zh.de_chain.** 这是一个十亿参数的开源小模型的微调的完整方案。 becomes
这是一套完整的微调方案，适用于一个十亿参数的开源小模型。

**zh.light_verb.** 我们正在对系统进行全面测试，并计划在周五进行配置调整。 becomes
我们正在全面测试系统，并计划在周五调整配置。 正在 stays 正在, and 计划 stays
计划. In formal registers 进行 may remain.

**zh.bei_stack.** 该问题被社区多次报告，被认为可能与内存泄漏有关，但原因尚未确认。
becomes 社区多次报告这个问题。它被认为可能与内存泄漏有关，但原因尚未确认。
被认为有关 does not mean 导致. Do not assume that the reporter also judged the
cause.

**zh.suizhe_opener, yue.era_opener.** 在技术不断发展的时代背景下，本文讨论文稿校对。
becomes 本文讨论文稿校对。
- Keep: 随着文件数量增加，检索时间也在增长。(A real trend.)

**zh.cliche_close.** 总而言之，让我们拭目以待，期待更多可能。团队计划在周五继续测试。
becomes 团队计划在周五继续测试。
- Keep: 综上，两种方案都无法满足离线要求，暂不采用。(A real conclusion.)

**zh.zero_subject_para.** A paragraph that is not the first one opens with 听起来,
值得注意的是 or 关键在于 and has no back-reference. Add 这 or name the thing being
commented on. Do not reorder paragraphs.

## 翻译腔 (translationese, zh.tl.\*)

Translationese on its own does not make a text sound generated. Only these five
structures (`actionable: true`) justify an edit. The other markers are
informational only.

1. **Long pre-modifier (zh.tl.long_premodifier).** 这是一个能够让团队在不增加人力的情况下显著提升审核速度的工具。
   becomes 这个工具能显著提升审核速度，不需要增加人力。 Keep all the information.
2. **当…时 clause (zh.tl.when_clause).** 当所有人都能用工具写文章时，内容本身就不再稀缺。
   becomes 所有人都能用工具写文章，内容本身就不再稀缺。 Keep it when the time point
   is needed. 的时候 is colloquial and fine.
3. **Topic shell (zh.tl.topic_shell).** 对于早期团队来说，招人是最难的事。 becomes
   早期团队最难的事是招人。 Keep it when the shell limits the scope.
4. **Sentence-initial connective (zh.tl.sentence_initial_connective).**
   此外，成本也是一个需要考虑的因素。 becomes 成本也得考虑。 Keep a signpost that
   the argument really needs.
5. **这意味着 restatement (zh.tl.this_means).** 留存率涨到了 72%。这意味着产品找到了方向。
   becomes 留存率涨到 72%，产品找到了方向。 Keep it when a new conclusion follows.
   Do not upgrade the claim ("意味着" stays an inference, not a proof).

These are never reasons to edit: abstract passives (被认为), nominalisation,
long sentences, 在…过程中, 如果…的话, 并且/而且, 正是, 一系列的, 扮演…角色,
以一种…的方式, and 使得…能够. Established legal, government and technical
wording also stays.

## Cantonese register checks (yue.\*)

**yue.register_mix.** 書面語 and 口語 mixed inside one sentence by accident:
我們今日去咗睇展覽 becomes 我哋今日去咗睇展覽 in a yue text, or
我們今日去了看展覽 in a zh-Hant-HK text. Follow the target register. If the owner
mixes on purpose, keep it.

**Particle overuse (no regex).** 啦, 喎 and 囉 attached to every sentence make
the text read like a template. Keep the particles the voice uses. Do not add new
ones.

**Cantonese colloquial markers (yue.colloquial_markers).** These show the
register. They are never errors.
