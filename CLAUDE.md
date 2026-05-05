# notes

## Git workflow

**Никогда не коммитить напрямую в `main`.** Любое изменение — через ветку + PR.

### Старт работы (каждый раз, когда начинается задача)

Если текущая ветка `main` и рабочее дерево чистое:
```bash
git checkout main && git pull
git checkout -b <type>/<kebab-case-description>
```

### Имена веток

| Тип | Когда | Пример |
|---|---|---|
| `feat/` | Новая фича для пользователя | `feat/yandex-disk-upload` |
| `fix/` | Исправление бага | `fix/whisper-chunk-leak` |
| `refactor/` | Внутренние изменения без смены поведения | `refactor/split-downloader` |
| `docs/` | Только документация | `docs/env-vars-reference` |
| `test/` | Только тесты | `test/callback-handlers` |
| `chore/` | Зависимости, конфиги, CI | `chore/bump-aiogram` |
| `perf/` | Оптимизация производительности | `perf/cache-transcriptions` |

Имена короткие, в нижнем регистре через дефис.

### Commit messages — Conventional Commits

Формат: `<type>(<scope>): <imperative description>`

- `scope` опционален: модуль/область (`handlers`, `config`, `transcriber`)
- Описание — в императиве, без точки в конце, до ~70 символов
- Тело (через пустую строку) — объясняет **почему**, не **что**

Примеры:
```
feat(handlers): add Yandex Disk link support
fix(transcriber): release temp chunk files on exception
docs: update README with deploy verification steps
refactor(config): move defaults to a typed Defaults class
test(text): cover TTL boundary at exactly CACHE_TTL
chore: bump aiogram to 3.15.1
```

Типы: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`.

### Перед открытием PR

1. Прогнать тесты — все должны быть зелёные
2. Сверить `README.md` с текущим состоянием кода
3. `git push -u origin <branch>`

### Открытие PR через `gh`

```bash
gh pr create --title "<type>(<scope>): краткое описание" --body "$(cat <<'EOF'
## Summary
- <что и зачем>

## Test plan
- [ ] tests pass
- [ ] <manual checks, если нужны>
EOF
)"
```

PR-титл и тело должны соответствовать Conventional Commits, т.к. они станут текстом
squash-коммита в `main` после мерджа (так настроен репо).

### Мердж

Только **squash merge**. Merge commits и rebase merges запрещены:
```bash
gh pr merge --squash --delete-branch
```

Ветка удалится на GitHub автоматически. Локально — вернуться на main и удалить ветку:
```bash
git checkout main && git pull
git branch -d <branch>
```

### Итог

`git log main --oneline` должен быть прямой вертикалью из Conventional Commits-титлов.
Никаких merge commits, никаких WIP'ов, никаких веток в истории main.
