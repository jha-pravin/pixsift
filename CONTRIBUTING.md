# Contributing

Thanks for helping improve PixSift. Bug reports and ideas are welcome as GitHub issues. Please report security
problems privately (see [SECURITY.md](SECURITY.md)).

## License of contributions

PixSift is source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE.md): free for personal
and other noncommercial use, while commercial rights stay with the author, who may offer PixSift (or paid
editions of it) commercially.

So that this stays possible, **by opening a pull request you agree that**:

1. you wrote the contribution, or otherwise have the right to submit it; and
2. you grant Pravin Jha a perpetual, worldwide, royalty-free, irrevocable license to use, modify, sublicense and
   distribute your contribution under any terms, including commercial ones, while it remains available to everyone
   under this repository's license.

If you can't agree to this, please open an issue describing the change instead.

## Development

See the README for setup. Before opening a pull request:

```bash
cd backend && .venv/bin/pytest
cd frontend && npx tsc -b && npx oxlint src
```
