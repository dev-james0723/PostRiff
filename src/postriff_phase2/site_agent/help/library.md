---
documentId: help_library
sourceType: product_help
title: Library
summary: Private images you can attach to posts.
routeFamilies: [library]
locales: [en]
productVersion: 2026.09
effectiveFrom: 2026-09-24
visibility: workspace
owner: product
topic: library
keywords: [library, image, media, upload, photo, 圖片, 媒體, 相, 上載]
---
# Library

The [Library](/app/library) holds images for your posts.

## Private by default

Images live in private storage and are served only to members of this workspace, through the API.

## Exact media

Every image is stored with its hash. A post records the exact hash it was approved with, so what publishes is what was reviewed.

## What is accepted

JPEG or PNG, up to 8 MB, 320–4096 px per side and at most 16.7 megapixels. Each image is decoded and re-encoded as JPEG with its metadata removed. Video is not accepted in this release.

## Used and unused

An image counts as used when a publishing job in any state, or a review waiting for approval, records it.
