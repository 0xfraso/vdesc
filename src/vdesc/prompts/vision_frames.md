You are analyzing consecutive frames sampled every few seconds from a video.
Context: {context}

For EACH frame, output a markdown section '## Frame @ mm:ss' containing:
1. **Scene**: what is shown (speaker, animation, UI, diagram, code editor, engine view...).
2. **Visible text/code**: transcribe ALL readable text VERBATIM. Code must be copied exactly
inside a fenced code block with the correct language tag. Preserve indentation, variable
names, comments and symbols. If code scrolls or is partially visible, transcribe exactly
what is readable and mark unreadable parts as [illegible].
3. If the frame shows the same screen as a previous frame with small changes, describe only
what changed plus any newly readable text.

Be exhaustive about visible code and settings panels - they will be merged with the transcript.
