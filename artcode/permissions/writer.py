from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml

from .models import PermissionAction
from .rules import PermissionRule, PermissionRuleError, RuleLoader, rules_document


class RuleWriter:
    def __init__(self, loader: RuleLoader) -> None:
        self.loader = loader

    def write_exact(self, match: str, action: PermissionAction) -> None:
        path = self.loader.paths.local
        try:
            new_rule = PermissionRule.parse(match, action.value)
            rules = [rule for rule in self.loader.load_file(path) if rule.match != match]
            rules.append(new_rule)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temp_path = Path(raw_temp)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    yaml.safe_dump(
                        rules_document(rules),
                        handle,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                RuleLoader(
                    type(self.loader.paths)(
                        user=Path("/nonexistent"),
                        project=Path("/nonexistent"),
                        local=temp_path,
                    )
                ).load_file(temp_path)
                os.replace(temp_path, path)
            finally:
                temp_path.unlink(missing_ok=True)
        except PermissionRuleError:
            raise
        except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
            raise PermissionRuleError(path, str(exc)) from exc
