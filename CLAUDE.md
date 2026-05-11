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

### Security
- Work like a senior software engineer while writing code and always prioritize on security.
- Make sure to always add security measures while designing and creating API's.

### Verification before done
- Never mark a task complete without proving it works
- Diff behaviour between main and your changes when relevant
- Ask yourself : "Would a staff engineer approve this?"
- When given a bug report : just fix it
- For bugs, dont just scratch the surface. Dive into the root cause and start fixing from there.
