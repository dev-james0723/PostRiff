# Post Doctor golden set: labeling guide

Phase 0 needs about 200 labeled posts or drafts, roughly half Traditional Chinese (Cantonese) and half English. Your labels are the ground truth that decides whether Jev is accurate enough for each Post Doctor dimension, in each language. Expect about three hours.

## What to label

Use real posts: your own published posts, drafts you never published, and posts from creators you respect. Mix strong and weak examples. Include some posts you think are bad; a set of only good posts cannot teach the levels.

Do not include anyone's private messages or personal data. Public posts by other people are fine for private evaluation; they are never published or used to train a model.

## The file

Copy `golden-template.csv` and add one row per post. Delete the example row first.

| Column | Meaning |
|---|---|
| `id` | Any unique short name, for example `jh-001` |
| `platform` | `threads`, `instagram`, `x`, `linkedin`, `facebook`, `youtube`, `tiktok` or `other` |
| `lang` | `zh-HK`, `zh-TW`, `en` or another BCP 47 tag |
| `kind` | `post` (published) or `draft` |
| `text` | The full text in double quotes; for a video, the caption plus the first lines of the script |
| dimension columns | A level from 1 to 4, or blank if you cannot judge |
| `better_than` | Optional: the `id` of another row this one is clearly better than overall |
| `notes` | Optional: anything that explains an unusual label |

## Levels

Use the same four levels Post Doctor will show: 1 = weak (弱), 2 = medium (中), 3 = strong (強), 4 = very strong (好強).

| Dimension | Ask yourself |
|---|---|
| `hook` 開頭 | Does the first line make a specific promise with a concrete detail, and does the post deliver it? |
| `audience` 觀眾啱唔啱 | Is this a real problem for the intended audience, in their words, at their level? |
| `novelty` 新意 | Is there a first-hand observation or a fresh angle on a common belief? |
| `specificity` 具體程度 | Are there real examples, numbers, steps, rather than vague adjectives? |
| `shareability` 分享價值 | Would someone send this to a specific person? Does it stand alone with one takeaway? |
| `conversation` 對話潛力 | Does it invite genuine replies or take a respectful position, without bait? |
| `clarity` 清晰 | One main idea, plain language, easy on a phone? |
| `emotion` 情緒拉力 | Is there a specific feeling and clear stakes for the reader? |
| `evidence` 證據 | Is the main claim backed by experience, data or a named source, with no unsourced facts? |

The five core dimensions for the Phase 0 gate are hook, audience, novelty, specificity and shareability. Label these on every row; the other four are welcome but optional.

## Checking and handing over

Run the validator from the repository root; it reports every problem with its row number and changes nothing:

```bash
PYTHONPATH=src python3 -m postriff_phase2.growth.golden validate path/to/your-labels.csv
```

Keep the finished file outside the repository (for example in your Documents folder) and tell Claude its path. Labels stay on your Mac; the evaluation runs locally and only the posts' text is sent to the models being compared, under the US$20 test cap.
