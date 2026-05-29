# ADR 008 — Two-form block decorator: @cms.block vs @block

**Status:** Accepted  
**Date:** 2026-05-28

---

## Context

Blocks can be defined in several contexts:

1. **Inline with an application** — a project defines its own blocks and uses them directly
2. **Shared internal library** — a team's shared block package used across multiple projects
3. **Third-party pip package** — a community block package installed by anyone

These contexts have different registration needs. A block defined inline should be registered immediately. A block in a shared package shouldn't auto-register anywhere — it should be available for explicit registration into whatever CMS instance the consumer creates.

---

## Decision

Two decorator forms with meaningfully different behavior:

**`@cms.block("name")` — first-party, immediate registration**
```python
cms = CMS(...)

@cms.block("hero")
class HeroBlock:
    title: str = TextField(required=True)
```
Defines the block and immediately registers it into `cms`'s registry. For inline application blocks.

**`@block("name")` — standalone, deferred registration**
```python
from starlette_cms import block

@block("gallery")
class GalleryBlock:
    heading: str = TextField(label="Gallery title")
```
Marks the class as a block definition (sets `__block_type__ = "gallery"`) but registers it nowhere. For library/package blocks that will be registered explicitly by the consumer.

Registration is always explicit for standalone blocks:
```python
cms.register_block(GalleryBlock)
cms.register_blocks([GalleryBlock, TestimonialBlock])
import my_block_package; my_block_package.register(cms)
```

---

## Rationale

**Auto-registration at import time is wrong for packages.** If `@block("gallery")` automatically registered into some global registry when the module was imported, a package author couldn't control which CMS instance their blocks end up in. Python imports are side effects — auto-registration on import is a well-known anti-pattern.

**Explicit registration makes the block set visible.** In application code, you can read `cms.register_blocks([...])` and immediately know what content types the CMS supports. Auto-discovery via entry points is opt-in (`discover_blocks=True`) for the "install and it works" convenience case — it's never the default.

**The `@cms.block` form is ergonomic for the common case.** Most application developers define blocks inline and want immediate registration. Making them call `cms.register_block(HeroBlock)` after every `@block` decoration adds noise with no benefit.

**Block type names are a data contract.** They're stored in document JSON in the database. Silent collision — last-write-wins — would silently corrupt stored content. The explicit registration API with `BlockRegistrationError` on collision makes this contract visible and enforced.

---

## Consequences

- Third-party block packages **must** use `@block()` (the standalone form) and expose a `register(cms)` function following the convention in section 5 of the starlette-cms spec
- Application blocks **should** use `@cms.block()` for ergonomics, but `@block()` + `cms.register_block()` is equally valid
- Block type names must be stable across versions of a package — renaming a block type in a minor version is a breaking change that corrupts stored documents. This is documented prominently in the block authoring guide.
