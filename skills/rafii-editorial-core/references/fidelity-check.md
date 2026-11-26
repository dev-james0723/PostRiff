# Fidelity check

Run this list against the original before returning an edit. The product runs
a mechanical version of the same list afterwards and shows the author a
reminder for each item that fails. A reminder does not stop the edit, but it
tells the author the edit cannot be trusted as written, so aim for none.

## The list

1. **Numbers.** Every number, unit, price and percentage in the original is in
   the result, written the same way ("3" stays "3", not "three"). The result
   has no number the original lacks.
2. **Dates and times.** Every date, weekday, time and deadline is unchanged.
3. **Names.** Every person, organisation, product and place is spelled and
   capitalised as before, and no new name appears.
4. **Links.** Every URL, @handle, #hashtag and email address is identical,
   character for character. None was added, dropped or moved into a sentence
   where it reads differently.
5. **Quotations.** Text inside quotation marks is word for word the same, and
   still belongs to the same speaker. No new quotation appears.
6. **Negation.** Count the negatives. A "not", "never", "no", 不, 沒, 未, 唔 or 冇
   that carried meaning is still there.
7. **Uncertainty.** "May", "might", "about", "probably", "so far", 可能, 大約,
   或許 and 暫定 are still there with the same strength. Nothing became
   "definitely", "certainly", "always", 一定 or 肯定.
8. **Attribution.** "According to", "said", "reported", 表示, 指出 and 根據 still
   point at the same source.
9. **Conditions and commitments.** "If", "unless", "only", 如果, 除非 and 只有 are
   still attached to the same claim. A plan is still a plan and nothing new is
   promised.
10. **Experience.** The result has no story, feeling, thanks, praise,
    credential or result that the original lacks.
11. **Language.** The result is in the same language and script. Traditional
    characters were not converted to Simplified or the reverse, written
    Cantonese was not turned into standard written Chinese, and words in
    another language are still in that language.
12. **Scope.** For a selection, only the passage came back. For a whole text,
    nothing was cut that the request did not ask to cut.

## Invented examples

Original: "We may reopen on 3 March, according to the landlord. Tickets are
$25 at rafii.example/tickets."

- Good (Direct): "According to the landlord, we may reopen on 3 March.
  Tickets: $25 at rafii.example/tickets."
- Fails 7 and 8: "We reopen on 3 March. Tickets are $25 at
  rafii.example/tickets."
- Fails 10: "We are thrilled to reopen on 3 March, according to the landlord!"
- Fails 4: "Tickets are $25 on our site."

Original: 「活動暫定於10月31日舉行，名額只有40個，報名請到 @harbourclub。」

- Good (Warm): 「活動暫定於10月31日舉行，名額只有40個。想參加的話，歡迎到
  @harbourclub 報名。」
- Fails 7: 「活動將於10月31日舉行，名額只有40個。」
- Fails 1 and 9: 「活動暫定於10月31日舉行，名額有限。」
- Fails 11: 「活动暂定于10月31日举行，名额只有40个。」

## When an item cannot be kept

If the requested tone cannot be reached without failing an item, keep the item
and give up that part of the tone. Say what was kept in the warning or note
field. An edit that is a little less warm is acceptable. An edit that changed
a date is not.
