# Inkloom AI / Offscript

Inkloom AI is an autonomous, pre-publication brand compliance review engine and human-in-the-loop governance tool. Creators submit draft content (text, image, PDF), an automated pipeline evaluates brand alignment and factual claims against guidelines, and designated managers and authorised reviewers provide final approvals before publication.

## Repository Layout
- `/backend`: FastAPI compliance service, models, pipeline, plug-ins, in-memory repository, and test suite.
  - See [backend/README.md](backend/README.md) for local run instructions, environment variables, OpenAPI endpoint details, and plugin replacement contracts.

## Current Project Status
- **Plug-ins**: Modular text-aware placeholder plug-ins (`retrieval`, `verification`, `brand_check`) with explicit failure flags.
- **Storage**: In-memory repository with a 200-item FIFO cap; `SupabaseRepository` remains an unimplemented placeholder.
- **Auth**: Role-based request model (`creator`, `manager`, `authorised_reviewer`) without authentication or login.
- **Multimodal**: File upload & byte-validation active; OCR text extraction is pending future roadmap integration.
