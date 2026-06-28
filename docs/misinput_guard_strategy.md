# Misinput Guard Strategy

Koe Kichi uses small local guards at each stage instead of relying on one large
AI rewrite. The Windows port currently implements the baseline guards below.

## Implemented

- Low-activity audio guard before transcription:
  - logs duration, RMS, peak, active seconds, and active ratio
  - skips empty, very quiet, or very low-activity recordings
  - does not paste or save history when skipped
- Known transcript hallucination trimming:
  - removes video-closing phrases such as `ご視聴ありがとうございました`
  - applies even when text correction is off
  - also applies to Gemini transcript sanitization
- Repetition cleanup:
  - collapses whole-text adjacent duplicates
  - trims long repeated suffixes such as repeated `じゃあ`
  - removes short-unit repetition only when the repeated span is long enough
- Streaming overlap merge:
  - removes exact overlap between prefetch windows
- URL punctuation exception:
  - avoids adding sentence punctuation to URL-only text
  - removes terminal Japanese punctuation after bare URLs and Markdown links
- History duplicate suppression:
  - skips saving the same final output twice within a short window

## Deliberately Conservative

- No fuzzy deletion.
- No broad semantic rewrite in the local guard.
- No blanket replacement of ordinary words such as `音楽`; contextual rules only.
- Audio compaction is not enabled yet, because cutting quiet speech incorrectly
  is worse than a small speed loss.

## Next Candidates

- Optional audio compaction with clear logging.
- Low-information output rejection using audio duration plus final text shape.
- More observed hallucination phrases in the block list.
