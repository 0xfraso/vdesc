Write the CODE DEEP-DIVE chapter for the video "{title}".

Output exactly this structure:
## Code Deep-Dive

Go through the frame analyses and extract EVERY piece of code and EVERY settings panel
that appeared anywhere in the video. For each distinct code snippet:
1. A '### <descriptive name>' heading,
2. The complete/final version of the code VERBATIM in a fenced code block with the
   correct language tag (reconstruct the full snippet from all frames where it appears;
   note any evolution across the video),
3. A line-by-line (or block-by-block) explanation: what it does, why it is needed,
   and how it connects to the narrator's explanation.

Then a final '### Engine & Inspector Settings' subsection listing every settings panel
visible in the frames verbatim (as tables or lists) with a one-line explanation of each
setting and its role.

Be exhaustive - include ALL code and settings visible anywhere, even fragments.
