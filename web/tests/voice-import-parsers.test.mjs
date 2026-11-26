/**
 * Export parsers (browser-side): six formats, layout generations, mojibake, unknown shapes. Every fixture is synthetic.
 *   node --test tests/voice-import-parsers.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { fixture, loadTs } from './fixtures/voice-import/load-ts.mjs';

const { detectExport, parseExport, combineExports, isPostFile, fileKind } = await loadTs('lib/voice-import/index.ts');
const { repairMojibake, stripHtml, decodeBytes } = await loadTs('lib/voice-import/text.ts');
const { parseCsv } = await loadTs('lib/voice-import/csv.ts');

const texts = (parsed) => parsed.items.map((item) => item.text);

test('mojibake: bytes written as \\u00XX escapes are restored; real Unicode and plain Latin-1 are left alone', () => {
  assert.equal(repairMojibake('ð\u009f\u0099\u0082'), '🙂');
  assert.equal(repairMojibake('ä»\u008aæ\u0099\u009a'), '今晚');
  assert.equal(repairMojibake('plain ascii'), 'plain ascii');
  // Any character above U+00FF means the string is already real text.
  assert.equal(repairMojibake('今晚 ð\u009f\u0099\u0082'), '今晚 ð\u009f\u0099\u0082');
  // A Latin-1 string that is not UTF-8 when read as bytes is real Latin-1, not mojibake.
  assert.equal(repairMojibake('café'), 'café');
});

test('Instagram: all three layout generations parse, and the caption comes from the post title, else the first media title', () => {
  const oldest = fixture('instagram/content/posts_1.json');
  const middle = fixture('instagram/your_instagram_activity/content/posts_1.json');
  const newest = fixture('instagram/your_instagram_activity/media/posts_1.json');
  assert.deepEqual(detectExport(oldest), { provider: 'instagram', layout: 'content' });
  assert.deepEqual(detectExport(middle), { provider: 'instagram', layout: 'activity-content' });
  assert.deepEqual(detectExport(newest), { provider: 'instagram', layout: 'activity-media' });

  const first = parseExport(oldest);
  assert.deepEqual(texts(first), ['Old layout caption about a recital 🎶']);
  assert.deepEqual(first.skipped, { unsupported: 0, empty: 1 });
  assert.equal(first.items[0].publishedAt, '2021-03-01T10:00:00.000Z');

  const second = parseExport(middle);
  assert.deepEqual(texts(second), ['Morning practice, slow scales first 🙂', '今晚練琴，慢慢嚟。']);
  // The post-level timestamp wins over the media one, as the post-level title does.
  assert.equal(second.items[0].publishedAt, new Date(1686000300 * 1000).toISOString());

  const third = parseExport(newest);
  assert.deepEqual(texts(third), ['Studio notes: a quiet hour before the lesson.', '今日教琴，學生進步咗 🎹', 'A caption already in real Unicode: 練習 ✅']);
  assert.deepEqual(third.skipped, { unsupported: 1, empty: 0 });
  assert.deepEqual(third.notes, []);
  for (const item of [...first.items, ...second.items, ...third.items]) {
    assert.match(item.externalId, /^export:instagram:\d+:[0-9a-z]+$/);
    assert.equal(item.permalink, undefined, 'the export carries no link, so none is invented');
  }
});

test('Instagram: the same post gets the same id from any layout, so a second upload updates instead of duplicating', () => {
  const file = fixture('instagram/your_instagram_activity/media/posts_1.json');
  const again = parseExport({ name: 'posts_1.json', text: file.text });
  assert.deepEqual(detectExport({ name: 'posts_1.json', text: file.text }), { provider: 'instagram', layout: 'posts' });
  assert.deepEqual(again.items.map((item) => item.externalId), parseExport(file).items.map((item) => item.externalId));
});

test('Facebook: the text is data[].post, never the system sentence in title; the timestamp is timestamp', () => {
  const current = parseExport(fixture('facebook/your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json'));
  assert.equal(current.provider, 'facebook');
  assert.equal(current.layout, 'activity-posts');
  assert.deepEqual(texts(current), ['We open the studio doors at ten on Saturday. Bring your questions.', '我們將於星期五推出新功能。']);
  assert.equal(current.items[0].publishedAt, new Date(1700000000 * 1000).toISOString());
  assert.deepEqual(current.skipped, { unsupported: 1, empty: 1 });
  assert.ok(!texts(current).some((text) => text.includes('Example Studio')), 'title is not post text');

  const older = fixture('facebook/posts/your_posts_1.json');
  assert.deepEqual(detectExport(older), { provider: 'facebook', layout: 'posts' });
  assert.deepEqual(texts(parseExport(older)), ['First week of the autumn term. Twelve new students and one very old piano.']);
});

test('Threads: text_post_app_text_posts entries become posts', () => {
  const file = fixture('threads/your_instagram_activity/threads/threads_and_replies.json');
  assert.deepEqual(detectExport(file), { provider: 'threads', layout: 'threads-and-replies' });
  const parsed = parseExport(file);
  assert.deepEqual(texts(parsed), ['Three things I tell every new student about practising.', '今晚練琴，慢慢嚟。']);
  assert.deepEqual(parsed.skipped, { unsupported: 0, empty: 1 });
  assert.equal(parsed.items[0].kind, undefined, 'the file mixes posts and replies without saying which is which');
});

test('X: the wrapper is stripped; full_text, id_str and created_at are read; reposts and replies are marked', () => {
  const file = fixture('x/data/tweets.js');
  assert.deepEqual(detectExport(file), { provider: 'x', layout: 'tweets' });
  const parsed = parseExport(file);
  assert.deepEqual(parsed.items.map((item) => [item.externalId, item.kind]), [
    ['1700000000000000001', 'original'],
    ['1700000000000000002', 'repost'],
    ['1700000000000000003', 'reply'],
    ['1700000000000000004', 'original']
  ]);
  assert.equal(parsed.items[0].text, 'Scales & arpeggios before coffee. Small habits > big plans.');
  assert.equal(parsed.items[0].publishedAt, '2024-02-18T12:33:11.000Z');
  assert.equal(parsed.items[0].permalink, 'https://x.com/i/web/status/1700000000000000001');
  assert.deepEqual(parsed.skipped, { unsupported: 1, empty: 1 });
});

test('X: note-tweet.js entries become posts with the full note text, and a note replaces its shortened post when both files are given', () => {
  const notes = fixture('x/data/note-tweet.js');
  assert.deepEqual(detectExport(notes), { provider: 'x', layout: 'note-tweet' });
  const parsedNotes = parseExport(notes);
  assert.deepEqual(parsedNotes.items.map((item) => item.externalId), ['note:1700000000000000900', 'note:1700000000000000901']);
  assert.match(parsedNotes.items[0].text, /ending with one piece we both enjoy\. The plan is short on purpose\.$/);
  assert.equal(parsedNotes.items[0].publishedAt, '2024-02-20T10:00:01.000Z');

  const [combined] = combineExports([parseExport(fixture('x/data/tweets.js')), parsedNotes]);
  assert.equal(combined.provider, 'x');
  const long = combined.items.find((item) => item.externalId === '1700000000000000004');
  assert.equal(long.text, parsedNotes.items[0].text, 'the post keeps its id and takes the full text');
  assert.ok(!combined.items.some((item) => item.externalId === 'note:1700000000000000900'), 'one piece of writing, one record');
  assert.ok(combined.items.some((item) => item.externalId === 'note:1700000000000000901'), 'a note with no short version stays');
  assert.equal(combined.items.length, 5);
});

test('X: other archive sections are not post files and are never parsed', () => {
  assert.equal(detectExport({ name: 'data/direct-messages.js', text: 'window.YTD.direct_messages.part0 = [{"dmConversation":{"messages":[]}}]' }), null);
  assert.equal(parseExport({ name: 'data/like.js', text: 'window.YTD.like.part0 = [{"like":{"tweetId":"1","fullText":"someone else"}}]' }), null);
  assert.deepEqual(detectExport({ name: 'data/tweet.js', text: 'window.YTD.tweet.part0 = [{"tweet":{"id_str":"9","full_text":"An older archive names the file tweet.js.","created_at":"Sat Feb 18 12:33:11 +0000 2023"}}]' }), { provider: 'x', layout: 'tweets' });
});

test('LinkedIn Shares.csv: quoted multi-line commentary, Date, ShareLink, and the post id from the link', () => {
  const file = fixture('linkedin/Shares.csv');
  assert.deepEqual(detectExport(file), { provider: 'linkedin', layout: 'shares' });
  const parsed = parseExport(file);
  assert.equal(parsed.items.length, 2);
  assert.equal(parsed.items[0].text, 'Three lessons from a term of teaching:\n\n1. Start slower than feels right.\n2. Say "well done" out loud, often.');
  assert.equal(parsed.items[0].externalId, 'urn:li:share:7100000000000000001');
  assert.equal(parsed.items[0].publishedAt, '2024-03-01T14:22:10.000Z');
  assert.equal(parsed.items[0].permalink, 'https://www.linkedin.com/feed/update/urn%3Ali%3Ashare%3A7100000000000000001');
  assert.equal(parsed.items[1].externalId, 'urn:li:ugcPost:7100000000000000003');
  assert.equal(parsed.items[1].text, '我哋下星期開新班，歡迎查詢。');
  assert.deepEqual(parsed.skipped, { unsupported: 0, empty: 1 });
});

test('LinkedIn: a file saved as Windows-1252 still decodes, and a header without the commentary column is an unknown shape', () => {
  const bytes = Uint8Array.from([...'Date,ShareLink,ShareCommentary\r\n2024-01-02 03:04:05,,"Caf'].map((c) => c.charCodeAt(0)).concat([0xe9], [...' set tonight"\r\n'].map((c) => c.charCodeAt(0))));
  const parsed = parseExport({ name: 'Shares.csv', text: decodeBytes(bytes) });
  assert.deepEqual(texts(parsed), ['Café set tonight']);
  assert.match(parsed.items[0].externalId, /^export:linkedin:/);
  assert.equal(decodeBytes(new TextEncoder().encode('﻿今晚')), '今晚', 'UTF-8 stays UTF-8 and the byte order mark is dropped');

  const odd = parseExport({ name: 'Shares.csv', text: 'When,Where\n2024,here\n' });
  assert.equal(odd.provider, 'linkedin');
  assert.deepEqual(odd.items, []);
  assert.deepEqual(odd.notes, ['unknown_shape']);
});

test('CSV rows: commas, doubled quotes and line breaks inside quotes; an unclosed quote never throws', () => {
  assert.deepEqual(parseCsv('a,b\r\n"x, y","say ""hi""\nnext"\r\n'), [['a', 'b'], ['x, y', 'say "hi"\nnext']]);
  assert.deepEqual(parseCsv('a,"never closed\nb,c'), [['a', 'never closed\nb,c']]);
  assert.deepEqual(parseCsv(''), []);
});

test('Mastodon outbox.json: public notes with HTML stripped; boosts counted; posts that are not public stay on the device', () => {
  const file = fixture('mastodon/outbox.json');
  assert.deepEqual(detectExport(file), { provider: 'mastodon', layout: 'outbox' });
  const parsed = parseExport(file);
  assert.deepEqual(parsed.items, [
    {
      externalId: '111000000000000001',
      text: 'Recital programme is set.\nDoors at seven & music at half past.\n\nSee https://example.com/programme #recital',
      publishedAt: '2024-04-01T08:00:00.000Z',
      permalink: 'https://example.social/@studio/111000000000000001',
      kind: 'original'
    },
    {
      externalId: '111000000000000005',
      text: '@someone Thank you, that helps.',
      publishedAt: '2024-04-05T08:00:00.000Z',
      permalink: 'https://example.social/@studio/111000000000000005',
      kind: 'reply'
    }
  ]);
  assert.deepEqual(parsed.local, { notPublic: 2, reposts: 1 });
  assert.deepEqual(parsed.skipped, { unsupported: 1, empty: 0 });
  assert.ok(!JSON.stringify(parsed).includes('followers only') && !JSON.stringify(parsed).includes('direct message'), 'no private text in the result');
});

test('HTML to text keeps paragraphs and line breaks and decodes entities once', () => {
  assert.equal(stripHtml('<p>One &amp; two</p><p>Three<br>Four</p>'), 'One & two\n\nThree\nFour');
  assert.equal(stripHtml('<p>&amp;lt;b&amp;gt; stays text &#x1F3B9; &#39;ok&#39;</p>'), '&lt;b&gt; stays text 🎹 \'ok\'');
  assert.equal(stripHtml(''), '');
});

test('an unrelated file is not an export; a known file with an unknown shape gives zero posts and a note; nothing throws', () => {
  assert.equal(detectExport({ name: 'settings.json', text: '{"name":"synthetic settings","items":[1,2,3]}' }), null);
  assert.equal(parseExport({ name: 'settings.json', text: '{"name":"synthetic settings","items":[1,2,3]}' }), null);
  assert.equal(parseExport({ name: 'notes.txt', text: 'just some words' }), null);

  const unknown = fixture('instagram-unknown/posts_1.json');
  assert.deepEqual(detectExport(unknown), { provider: 'instagram', layout: 'unknown' });
  const parsed = parseExport(unknown);
  assert.deepEqual({ items: parsed.items, skipped: parsed.skipped, notes: parsed.notes }, { items: [], skipped: { unsupported: 0, empty: 0 }, notes: ['unknown_shape'] });

  for (const [name, text] of [
    ['posts_1.json', '{"broken": '],
    ['outbox.json', '[]'],
    ['outbox.json', '{"orderedItems":"nope"}'],
    ['tweets.js', 'window.YTD.tweets.part0 = {"not":"an array"}'],
    ['tweets.js', 'window.YTD.tweets.part0 = [null, 3, "x", {"tweet": null}, {"tweet": {"id_str": 7, "full_text": 9}}]'],
    ['threads_and_replies.json', '{"text_post_app_text_posts":[null,{"media":"x"}]}'],
    ['your_posts_1.json', '[{"timestamp":"soon","data":"none"}]'],
    ['Shares.csv', '']
  ]) {
    const result = parseExport({ name, text });
    assert.ok(result && Array.isArray(result.items), `${name} is recognised by name`);
    assert.equal(result.items.length, 0, `${name} yields no posts`);
    assert.ok(result.notes.length > 0 || result.skipped.unsupported > 0, `${name} says why: ${text}`);
  }
});

test('folder picks open only post files; other picks are sorted by what they are', () => {
  for (const name of ['your_instagram_activity/media/posts_1.json', 'content/posts_12.json', 'your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json', 'posts/your_posts_2.json', 'your_instagram_activity/threads/threads_and_replies.json', 'data/tweets.js', 'data/tweets-part1.js', 'data/note-tweet.js', 'Shares.csv', 'outbox.json']) {
    assert.equal(isPostFile(name), true, name);
  }
  for (const name of ['your_instagram_activity/messages/inbox/someone/message_1.json', 'data/direct-messages.js', 'media/posts/202501/photo.jpg', 'likes.json', 'Connections.csv', 'data/account.js']) {
    assert.equal(isPostFile(name), false, name);
  }
  assert.equal(fileKind('export.zip'), 'archive');
  assert.equal(fileKind('your_instagram_activity/media/posts_1.html'), 'html');
  assert.equal(fileKind('posts_1.json'), 'text');
  assert.equal(fileKind('tweets.js'), 'text');
  assert.equal(fileKind('Shares.csv'), 'text');
  assert.equal(fileKind('photo.jpg'), 'other');
});

test('combining files of one platform sums the counts and keeps one record per id', () => {
  const file = fixture('instagram/your_instagram_activity/media/posts_1.json');
  const combined = combineExports([parseExport(file), parseExport(file), parseExport(fixture('instagram/content/posts_1.json')), parseExport(fixture('mastodon/outbox.json'))]);
  assert.deepEqual(combined.map((group) => group.provider), ['instagram', 'mastodon']);
  assert.equal(combined[0].items.length, 4);
  assert.deepEqual(combined[0].skipped, { unsupported: 2, empty: 1 });
  assert.equal(combined[0].files, 3);
  assert.deepEqual(combined[1].local, { notPublic: 2, reposts: 1 });
});
