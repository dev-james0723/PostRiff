# YouTube channel switch — connected and verified

Target: James Au, @jamesau0723, UCkYfh6HmmGE7TH79UgDZ38Q, controlled through hinsingau.pianist@gmail.com.

The target channel was using YouTube Studio channel permissions, which are unavailable to the YouTube Data API. The owner opted out of Studio permissions, restoring Brand Account OAuth. Google exposes the backing Brand Account under its legacy account label, DFestival 青年鋼琴家藝術節. The OAuth token's `channels.list(mine=true)` result independently matched UCkYfh6HmmGE7TH79UgDZ38Q and returned James Au / @jamesau0723.

The broker accepts the Brand Account OAuth subject only when the YouTube API returns the exact requested channel ID and the exact approved read-only plus upload scopes. A different channel fails closed.

Live Studio state after OAuth and a separate Check connection refresh:

- identity connected
- publish-ready
- account label: hinsingau.pianist@gmail.com
- channel: James Au / @jamesau0723
- channel ID: UCkYfh6HmmGE7TH79UgDZ38Q
- last independent verification: 2026-09-14T04:25:46.356Z

Validation: installed broker suite 18/18 passed; source broker suite 22/22 passed; project verifier passed. Studio is running and healthy.

No video, Short, community post, schedule, or other publication was submitted.
