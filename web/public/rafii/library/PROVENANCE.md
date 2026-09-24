# Content Library artwork: provenance

Source archive: `docs/design/reference/rafii-v9/rafii-prototype-v9-source.zip` (SHA-256 `285f85ffeb9f04cb9f5d70b29eaab237ccb5d7db336f932d3ad83c9e767bb2fa`), the approved Rafii v9 prototype.
Inside it: `rafii-prototype-v9/src/assets/thumbnails/*.svg` (large 8:5 illustrations) and
`rafii-prototype-v9/src/assets/glyphs/*.svg` (compact 1:1 glyphs). Metadata: `taxonomy-data.json`
(version 1.0.0) and `library-data.json` (version 7.0.0, reviewed 2026-09-22).

Every file here is byte for byte the archive file; the hash column is the SHA-256 the prototype recorded as
`content_hash`, re-computed at port time. The prototype describes the art as `original_deterministic_svg`
(drawn for the prototype, no stock imagery, external URLs or fonts). Rendering namespaces the internal SVG ids
(`paper`, `shadow`) per instance and adds motion classes at render time (`SemanticIllustration`); the files
stay untouched. `legacy-fallback.svg` is for explicitly legacy or missing ids only.

Regenerate with `node web/src/lib/content-library/port.mjs`.

| File | Archive path | SHA-256 |
|---|---|---|
| `thumbnails/status_update.svg` | `assets/thumbnails/status_update.svg` | `bef8980b41048dc40f379f4965ac8591255f7545811bb2897e814dc35c498482` |
| `glyphs/status_update.svg` | `assets/glyphs/status_update.svg` | `70a4e747dcdcb7bb6172271d0110b5fcbc120c7dbc387e19569009bfe37e4d7e` |
| `thumbnails/announcement.svg` | `assets/thumbnails/announcement.svg` | `9076b40d045b2feae95b23600303130d7642cdad6198f1c3cd90f674787e5726` |
| `glyphs/announcement.svg` | `assets/glyphs/announcement.svg` | `82799867958b9550730a9cc4740f8183222805ce5a7059be6dd7a090597950ab` |
| `thumbnails/news_curation.svg` | `assets/thumbnails/news_curation.svg` | `8cda4c56a07893279a567d87281022f496b25fdb84f38235c1bceb5949b4a190` |
| `glyphs/news_curation.svg` | `assets/glyphs/news_curation.svg` | `24b9ae62d6f00bab8154a80a5016e2024b57598828134e0f91b4c32974e78cf0` |
| `thumbnails/opinion_commentary.svg` | `assets/thumbnails/opinion_commentary.svg` | `f1c82f31ad401ab21fb1b67d352d42f3cc375759fd8fa3bb106fc6ac5799ae16` |
| `glyphs/opinion_commentary.svg` | `assets/glyphs/opinion_commentary.svg` | `5307d7664e96dd265a5db733c7202e4f903f3172528d2aa3816903e80352ab2d` |
| `thumbnails/quote.svg` | `assets/thumbnails/quote.svg` | `a2e0d8c046432f34334134c8eb29a810cfe647042e39240a3d8d830fbf660b22` |
| `glyphs/quote.svg` | `assets/glyphs/quote.svg` | `7d5225766f8373d9166d4619a4ed9150feea7b58e96fe8d299057b4af7b78ccf` |
| `thumbnails/question_prompt.svg` | `assets/thumbnails/question_prompt.svg` | `e84f6c9c91f4501a37de1792b91c269d21f47b9b2fc2e4b1ef91f44b8b15afcf` |
| `glyphs/question_prompt.svg` | `assets/glyphs/question_prompt.svg` | `d1f654f8832df43d531044f9a12ac0e144f59e077dd844b630ada76a1332ecf7` |
| `thumbnails/poll_quiz.svg` | `assets/thumbnails/poll_quiz.svg` | `f3f0c19615e14d2c0290372f253cdc07b998604e41190ea236c86c9a94d4c4e9` |
| `glyphs/poll_quiz.svg` | `assets/glyphs/poll_quiz.svg` | `6dec3e53972fa63501acb0f3319f34ba8a349f9e4b09cd6207f645390ed0351a` |
| `thumbnails/how_to.svg` | `assets/thumbnails/how_to.svg` | `4d706d69a705cff9c5e52b93e8efb8f474a63c82744673da95bbe6a6610338f0` |
| `glyphs/how_to.svg` | `assets/glyphs/how_to.svg` | `95db2bfc593a7aa1503d9a6c1e49bf3fffe184bcc99d1a5c1b6d52d3ab0dfc5d` |
| `thumbnails/educational_explainer.svg` | `assets/thumbnails/educational_explainer.svg` | `2683d1fc245337f119146ff08103625d3f6a728ab1fc3ae871b44193e9f5ef15` |
| `glyphs/educational_explainer.svg` | `assets/glyphs/educational_explainer.svg` | `bd9b960dd67592a9e6edfeb305a48c8ca418f6d1339c61bf02cfda8b798f0e9e` |
| `thumbnails/list_checklist.svg` | `assets/thumbnails/list_checklist.svg` | `42fe2395c98de93adea9ccb05dd5d6539779b55cbc0cd291224f5a2defce2600` |
| `glyphs/list_checklist.svg` | `assets/glyphs/list_checklist.svg` | `1a4de2a52b21f0b3ab034e734951cbf5706094a2279868ff47d2aeef9a447456` |
| `thumbnails/review_comparison.svg` | `assets/thumbnails/review_comparison.svg` | `18984339256cde99fc95aaeb1db17faabed7fbfcbb72c567abeca368f467904a` |
| `glyphs/review_comparison.svg` | `assets/glyphs/review_comparison.svg` | `38516e77ea13fb983db7097d51910ccb27a2040fa9934d575a1ceb943b518cd7` |
| `thumbnails/resource_roundup.svg` | `assets/thumbnails/resource_roundup.svg` | `bd8fd2817853f675aa1e2949f7221e1a4205dc74a43010ba2adfd281b4d2fb54` |
| `glyphs/resource_roundup.svg` | `assets/glyphs/resource_roundup.svg` | `816db83975e9f8836633c6e9dd352356f6256424c252e1e23071563b232b4b49` |
| `thumbnails/product_service_showcase.svg` | `assets/thumbnails/product_service_showcase.svg` | `e86b7813beecaca653d3f4ed5ef393168117c0f16ae37061b89d4a70e3af4423` |
| `glyphs/product_service_showcase.svg` | `assets/glyphs/product_service_showcase.svg` | `1956ff3a1ef6eeb9da035dd2c97534c73a024629f895a1645fb30a0aedd1d960` |
| `thumbnails/product_update.svg` | `assets/thumbnails/product_update.svg` | `a91b43fbd3df0d933104765af15e83053ed9dd232fb65688be98abfe3eee361c` |
| `glyphs/product_update.svg` | `assets/glyphs/product_update.svg` | `d9bf123ba5e7b67e04678b33968abbb70dcf737cb31e3a491a22fd1b671d5436` |
| `thumbnails/launch_release.svg` | `assets/thumbnails/launch_release.svg` | `d4ca83d7eb2827de4b1b8067c88939b557059c9f4507f9acfcc50ca390b1deea` |
| `glyphs/launch_release.svg` | `assets/glyphs/launch_release.svg` | `b4080c235fd25dbc40894a93989b2ea1012e4cfa0b191a09e2d3ec4521eb2a57` |
| `thumbnails/promotion_offer.svg` | `assets/thumbnails/promotion_offer.svg` | `87a33da499cfae89795781eb151a805fd3181a63d1264ef24298826015aa4a01` |
| `glyphs/promotion_offer.svg` | `assets/glyphs/promotion_offer.svg` | `b979b9019e07dc101fe5d95b64bea93837f7f95941a3da53531912529e9d192c` |
| `thumbnails/event_live.svg` | `assets/thumbnails/event_live.svg` | `eb6f9ea4019d927ac5e2de0b73cd83b72ea01eda8ab3008de9d7da3bada28c8e` |
| `glyphs/event_live.svg` | `assets/glyphs/event_live.svg` | `08f01e6c131515c14dc336fb33102b932624618c51bc4a873614182d2effe0e4` |
| `thumbnails/behind_the_scenes.svg` | `assets/thumbnails/behind_the_scenes.svg` | `89691bbf229cc1db1e52fff2e8c4c54b931c878898fac5fbbee3bdd6fbe982ab` |
| `glyphs/behind_the_scenes.svg` | `assets/glyphs/behind_the_scenes.svg` | `171c81fea2743e8d77c61ce349b89ee087784c769172412b34ce558227ed85a0` |
| `thumbnails/personal_lifestyle.svg` | `assets/thumbnails/personal_lifestyle.svg` | `459f7364d5595043331a56b7af0032edf4807a70b67464549692154a2fad6d73` |
| `glyphs/personal_lifestyle.svg` | `assets/glyphs/personal_lifestyle.svg` | `e509ada67774edd31a4e333cec6f1753b7d766c47c018d4f428c1518fd9b93ee` |
| `thumbnails/milestone.svg` | `assets/thumbnails/milestone.svg` | `548669d3e256ea3102902ed8630dba8f73a9d8c66701f6d6b454efcbc191bab0` |
| `glyphs/milestone.svg` | `assets/glyphs/milestone.svg` | `eedce3817f291abd6ce3ebd5d8bc2bdef02471d36b34dfc3c15ad60b5bbddc29` |
| `thumbnails/ugc_testimonial.svg` | `assets/thumbnails/ugc_testimonial.svg` | `a34cd4a7c23fcc5cfc4d0f32106d2bcf881695855c353db4a02ebb30d4b2bab5` |
| `glyphs/ugc_testimonial.svg` | `assets/glyphs/ugc_testimonial.svg` | `cba9f86a9b02a7ac0035fc4a9cbfaa431945ee3378927e1beddad856a3b4a14e` |
| `thumbnails/case_study.svg` | `assets/thumbnails/case_study.svg` | `bf0957c1965186869602b8d414f8153a1bd8af3ad0808ffc981f4995a595e701` |
| `glyphs/case_study.svg` | `assets/glyphs/case_study.svg` | `a68ef939ab5d34871547d826f446c02bae33b9d0c498a6ed8ebdb4f0c1233f47` |
| `thumbnails/qa_faq.svg` | `assets/thumbnails/qa_faq.svg` | `fe45389e1e958f3416128a9d4cb003ab66c6cc910956977fc8e6156adc23dd22` |
| `glyphs/qa_faq.svg` | `assets/glyphs/qa_faq.svg` | `39c2375426753dfad71a2d2a8bf1dcda7eac915bc1cbf42ce781c31d6268e52e` |
| `thumbnails/community_announcement.svg` | `assets/thumbnails/community_announcement.svg` | `2d7f56a7552bae8adb81503f5f3a64e84326700a6c17e792b796aadbf1ed178b` |
| `glyphs/community_announcement.svg` | `assets/glyphs/community_announcement.svg` | `10a0e8d621dfe727b95ccb7ced74045a3c885db42c55d2688f3d62648ef7fc52` |
| `thumbnails/cause_advocacy.svg` | `assets/thumbnails/cause_advocacy.svg` | `1f62e03c798f266313c79d6ab3b6e7d92e341bd0ccdff4972d450c8bbbb5b8ce` |
| `glyphs/cause_advocacy.svg` | `assets/glyphs/cause_advocacy.svg` | `733deefbad2b1398016eaf22aafed2e8eda2a84a46ba081040e3d6e71fc0b5a3` |
| `thumbnails/contest_challenge.svg` | `assets/thumbnails/contest_challenge.svg` | `bfc6e042a55b3a31ea08fa854e3e4b6c90e91c0d2622777e56dbee2f91defa0a` |
| `glyphs/contest_challenge.svg` | `assets/glyphs/contest_challenge.svg` | `71c1f5dbf52a6868b605715d8572a16db18454c37a5bdb3c556e307a61165b2e` |
| `thumbnails/job_recruitment.svg` | `assets/thumbnails/job_recruitment.svg` | `3835932686bdc988c6de596629771794355a1293c56417703b1a4d2f619b6be1` |
| `glyphs/job_recruitment.svg` | `assets/glyphs/job_recruitment.svg` | `687a0c442bfe4d0c3bffb438db719564ba8c10561e1263e490fbc5a1f9a5586b` |
| `thumbnails/article_blog_newsletter.svg` | `assets/thumbnails/article_blog_newsletter.svg` | `82bef5604b4f7df6154b6af0b8e3b0f032bee6fdc36851c842a63eb432430eaf` |
| `glyphs/article_blog_newsletter.svg` | `assets/glyphs/article_blog_newsletter.svg` | `554c5ec84a6c4c15999766a17842fb3e0eb8fe95e9e8259742d855851b676800` |
| `thumbnails/recap_followup.svg` | `assets/thumbnails/recap_followup.svg` | `80b68bc0001308285c5d64972b7aa2db997f0fb510a3cd289233c1741a818310` |
| `glyphs/recap_followup.svg` | `assets/glyphs/recap_followup.svg` | `b307c018716e04f9787a256087d822cd177734ca5ea144a2452ce78713a4c024` |
| `thumbnails/reaction_reply.svg` | `assets/thumbnails/reaction_reply.svg` | `c934bcee8e2d0a852c6dd851b444626ab645a7ac598a503cb5232e067782d823` |
| `glyphs/reaction_reply.svg` | `assets/glyphs/reaction_reply.svg` | `f72a03b7e94eedda18416f9fec7e6987b2a26993ddca707aacddadfe5041349a` |
| `thumbnails/live_ama.svg` | `assets/thumbnails/live_ama.svg` | `a86de8a4d0d60fcce8e72cf296c0acc145f64dd36532ff3ed7d80b0a102d5ab0` |
| `glyphs/live_ama.svg` | `assets/glyphs/live_ama.svg` | `2c7934af22bb8b1665f7a7d1274db6d6f694d700595d23f24367490e9115d6b9` |
| `thumbnails/text.svg` | `assets/thumbnails/text.svg` | `8d7f2a8357146e0aba75ab3ebda699df09c87751e18d6928a798e577024a9a57` |
| `glyphs/text.svg` | `assets/glyphs/text.svg` | `a3b8f671e4569f2b12deda0cee1c628e834e5941d942c35c29b467e5399d6bb7` |
| `thumbnails/long_text.svg` | `assets/thumbnails/long_text.svg` | `653e439c408e634bc2d6af7a0b800a6666522dc4dc85b5a64ef2c5efeefa47bd` |
| `glyphs/long_text.svg` | `assets/glyphs/long_text.svg` | `d95b0a941de9b3abc0af0884abaaa23337ca57da013c147dc09103f86e8fe6ce` |
| `thumbnails/thread.svg` | `assets/thumbnails/thread.svg` | `b5199ed8117435f6d76a8a56db9939a2db9b68f8cd8d1b7bbd9447143f3951c9` |
| `glyphs/thread.svg` | `assets/glyphs/thread.svg` | `db7fab548544668cb4673597c1124cd47bb3ecc645a8e91c382f798ab143f455` |
| `thumbnails/image_caption.svg` | `assets/thumbnails/image_caption.svg` | `ebdf524d0a29484c98e8f6658e7a6a9579686752967efa125c102f5aad739b49` |
| `glyphs/image_caption.svg` | `assets/glyphs/image_caption.svg` | `aa67d4eed54e18a34b9c5c13ec87434cfd2eeeea221b072ae187eb7583ab1eb4` |
| `thumbnails/quote_card.svg` | `assets/thumbnails/quote_card.svg` | `b9b8bc0252094c259c9fa884b367e1e7e2e887dd277e863f3115ce06c5644ac5` |
| `glyphs/quote_card.svg` | `assets/glyphs/quote_card.svg` | `2a6315f4c97ce56453e21e36007d92b5c17b37b8c85a46007c681773ce617e3e` |
| `thumbnails/carousel.svg` | `assets/thumbnails/carousel.svg` | `76178b6e1bf592fabf5a1d3cadfcf5bf01a4ffacb8c2bef74f00fd1b5f08e049` |
| `glyphs/carousel.svg` | `assets/glyphs/carousel.svg` | `a721322e20c3caaf1dda2ee71a32d3b00c8096f46e5898bf4d61bf514d7978d5` |
| `thumbnails/link_preview.svg` | `assets/thumbnails/link_preview.svg` | `270c4c541e9074087a3e58ee050d081206a4a8bc2e3c8536215c8dedb2d7fded` |
| `glyphs/link_preview.svg` | `assets/glyphs/link_preview.svg` | `5ab9132ee60fb5267a1c09086a9c73834def8f2c2ca5a5589d707ce822916998` |
| `thumbnails/native_article.svg` | `assets/thumbnails/native_article.svg` | `4baa0c4ef6ac03b15bca3edbd21448591c401e729aeb06f810f09d76b10a8fd7` |
| `glyphs/native_article.svg` | `assets/glyphs/native_article.svg` | `93eecac2fd1486ad53cc9906a0523fa588e3dd1eb5eb4ba347d0e6dc7adc8a1f` |
| `thumbnails/document.svg` | `assets/thumbnails/document.svg` | `7fecacc5e33cb61671b6221936c180a8ac8ef134b045baedc400a275021438a1` |
| `glyphs/document.svg` | `assets/glyphs/document.svg` | `357f597f22f686ef64fca164fd826fc6dc4cf9100191e260ff38e2c34a57bf68` |
| `thumbnails/short_vertical_video.svg` | `assets/thumbnails/short_vertical_video.svg` | `2689d2e7701e08a7153a0413fb884b6b199cac8c31f24031d79cc93ca73f95dd` |
| `glyphs/short_vertical_video.svg` | `assets/glyphs/short_vertical_video.svg` | `307a0cc4663a7a0fa9aea26985d121bec0d0c791031766269fe66008ff0b47b1` |
| `thumbnails/long_video.svg` | `assets/thumbnails/long_video.svg` | `0e26a25e6a0f470a002fa6d7a5a69a9d34a51c0da7babe6fee2f8d25f95998ba` |
| `glyphs/long_video.svg` | `assets/glyphs/long_video.svg` | `c54f309824ad239830263aaac31bc3a3edd8b8133809bf9c02ecc2a7a712fed9` |
| `thumbnails/livestream.svg` | `assets/thumbnails/livestream.svg` | `db8628c0632975a6b2d4996111c63fa4bd734263095dc720bb0bcfa8ad4560d2` |
| `glyphs/livestream.svg` | `assets/glyphs/livestream.svg` | `e350be533686a8e30e8622860d1da4bed5d97589bdfd22cf2f8378372f3e06a2` |
| `thumbnails/story.svg` | `assets/thumbnails/story.svg` | `af2a4b79baef17b0dd9c7c8ce4a5777dbdd0e19e04d18805ac47883bb8cfe75f` |
| `glyphs/story.svg` | `assets/glyphs/story.svg` | `383e96cd6458ceca07c98b247f82a4c40140474ee298dca38fec45fa3734bc28` |
| `thumbnails/poll.svg` | `assets/thumbnails/poll.svg` | `75ff9e317099b082df14a275eb2124880e118f08f7e05447fa3911f850adfc03` |
| `glyphs/poll.svg` | `assets/glyphs/poll.svg` | `74b49de828dd776b44c4f5af650374fe6575859c1d8a4f2605e69caf78f21db3` |
| `thumbnails/quiz.svg` | `assets/thumbnails/quiz.svg` | `01b2dbbb8c1ab3b6c017b9ec15f0b09d89df1630c86dc724b0922f741c0cc7ce` |
| `glyphs/quiz.svg` | `assets/glyphs/quiz.svg` | `d911c3f1b9a6783018d21f5088535ce27a13cb98142aa590a7be963eec1aafc5` |
| `thumbnails/audio.svg` | `assets/thumbnails/audio.svg` | `55049deae17ab95fc495b605b41402d073faa1898c4f2f1b303c1d8a1dfa14b5` |
| `glyphs/audio.svg` | `assets/glyphs/audio.svg` | `ed93d03af89b464f3257e4c7b973bf261f8a995e197a256f4f7bc4059c10c9de` |
| `thumbnails/broadcast_message.svg` | `assets/thumbnails/broadcast_message.svg` | `e478c107aaa13d3653d6e0bf239e29c5125aba5fefd12e95f66f663a4de2602b` |
| `glyphs/broadcast_message.svg` | `assets/glyphs/broadcast_message.svg` | `3fb49c3e3987dccc0baffd9181696c9e1e4e1877868f539a6ed45cbebd84b162` |
| `thumbnails/community_message.svg` | `assets/thumbnails/community_message.svg` | `62c9821ff1c230bc2387aef07ad6c768342648301d74a26ff641a945a21b6174` |
| `glyphs/community_message.svg` | `assets/glyphs/community_message.svg` | `bee4c880f506a67f94ccfb4bbd55bf1a3c3f3388edbf38fae7969d1ed6d28c04` |
| `thumbnails/product_catalog.svg` | `assets/thumbnails/product_catalog.svg` | `f5ea6dd21d928d1a63217f1b85fa473c48844b4e0e94b89267399de28f29116d` |
| `glyphs/product_catalog.svg` | `assets/glyphs/product_catalog.svg` | `71d5394feb111a76366f36ae11d19b11d66a33d7445401d3596fc12201155f65` |
| `thumbnails/local_business_update.svg` | `assets/thumbnails/local_business_update.svg` | `6b4e26f9092170d377dac297bae5037afa76c8c7782c3bc9364d9dc78e64eb58` |
| `glyphs/local_business_update.svg` | `assets/glyphs/local_business_update.svg` | `a31ef58fe2d3163404896d6cc85d2d50ca58bdfa00b97c5beb04e37da698cc61` |
| `thumbnails/legacy-fallback.svg` | `assets/thumbnails/legacy-fallback.svg` | `2fd0230274e14eb3ee8b9b67e481c8a889b129f6322f4a603e98edff5b0b1ded` |
