# DOOM Engine Documentation

This folder contains reference documentation for the DOOM source code
(id Software, 1993 / open-sourced 1997, Linux port v1.10).

| Document | Description |
|---|---|
| [overview.md](overview.md) | Comprehensive codebase overview: layout, technologies, subsystems, key data structures |
| [architecture.md](architecture.md) | Technical architecture with 16 Mermaid diagrams (game loop, renderer pipeline, BSP tree, actor lifecycle, network protocol, etc.) |
| [formal-spec.md](formal-spec.md) | Formal specification in Z++ — abstract machine spec covering memory, WAD, geometry, actors, player, renderer, and networking |
| [hardware-analysis.md](hardware-analysis.md) | Hardware requirements (1993), concurrent instance estimates on 2026 devices, and a 30-year retrospective on what has been superseded vs. what still holds up |

## Quick Start

```bash
# Build the engine
cd linuxdoom-1.10
mkdir linux
make
# → linux/linuxxdoom

# Build the sound server
cd ../sndserv
make

# Run (requires an IWAD from a retail or shareware copy of DOOM)
./linuxdoom-1.10/linux/linuxxdoom -iwad /path/to/doom.wad
```

## Document Rendering

- **Mermaid diagrams** in `architecture.md` render natively on GitHub and in VS Code with the
  [Markdown Preview Mermaid Support](https://marketplace.visualstudio.com/items?itemName=bierner.markdown-mermaid) extension.
- **Z++ formal notation** in `formal-spec.md` uses Unicode mathematical symbols and renders best
  in a Markdown viewer with a monospace code font; for print output use Pandoc + LaTeX.
