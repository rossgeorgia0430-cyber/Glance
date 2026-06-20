# Glance-specific Everything SDK build

This directory contains the MIT-licensed Everything SDK source used to build
`glance/GlanceIndex64.dll`.

The SDK was changed so all six IPC window lookups target the private named
window class `EVERYTHING_TASKBAR_NOTIFICATION_(Glance)` instead of the default
Everything instance. This prevents Glance from attaching to, starting, or
depending on a user's desktop Everything process. Two unused MSI service helper
exports are inert in this build so the SDK can be built with TinyCC's compact
Win64 headers.

Rebuild with TinyCC 0.9.27 for Win64 from the repository root:

    tcc -m64 -shared -o glance/GlanceIndex64.dll vendor/everything_sdk/src/Everything.c -luser32 -lkernel32

The upstream SDK archive is available from
https://www.voidtools.com/Everything-SDK.zip.
