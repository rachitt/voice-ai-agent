### 1.About the application
- The goal is to create an end to end voice AI application, which is able to compete with Retell and Vapi. 
- For the tech stack, make sure to use the best technology, as the baseline we can start off with Deepgram, Elevenlabs, an open source LLM (this can change based on performance), React JS frontend and FastAPI backend.

### 2.Subagent strategy and Self Improvement
- Use subagents liberally to manage the main context window
- AFTER any correction from the user and learning: update `tasks/lessons.md`. Make sure to keep the learnings brief and the length of the file below 300 lines.
- Ruthlessly iterate on these lessons until failure rate drops.
- Review these lessons at the start of each session.

### Git operations
- While committing, keep commit messages short and concise and dont use co-authored tags.
- While executing tasks, try to work on multiple git worktrees to accelerate the dev process. 
- Create worktrees for features which are independent to avoid merge conflicts. Merging worktrees should happen sequentially as well.
- Create a new branch while working on a new feature
- Create a PR and do a full PR review before merging into main

### Security
- Work like a senior software engineer while writing code and always prioritize on security.
- auth on every endpoint, secrets via env vars not commits, input validation on WebSocket payloads, rate limits on the LLM/TTS proxies, PII handling for call recordings. 
- Voice AI has specific security shapes (recording consent, audio storage encryption, prompt injection via transcribed speech)

### Verification before done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself : "Would a staff engineer approve this?"
- When given a bug report : just fix it
- For bugs, dont just scratch the surface. Dive into the root cause and start fixing from there.

### Context management
- At the beginning of each session read `tasks/next_session.md`.

- at the end of a session, write a brief 2-3 line summary in `tasks/next_session.md` on the tasks completed in this session and clear the contents. In 5-6 lines outline the tasks for the next session.