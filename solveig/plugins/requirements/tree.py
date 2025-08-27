"""TreeRequirement plugin - Generate directory tree listings."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field

from solveig.schema.requirements.base import Requirement, validate_non_empty_path
from solveig.utils.file import Filesystem

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface
    from solveig.schema.results import TreeResult


class TreeRequirement(Requirement):
    """Generate a directory tree listing showing file structure."""
    
    path: str = Field(..., validator=validate_non_empty_path, description="Directory path to generate tree for")
    max_depth: int = Field(default=3, ge=1, le=10, description="Maximum depth to traverse")
    show_hidden: bool = Field(default=False, description="Include hidden files and directories")
    
    def create_error_result(self, error_message: str, accepted: bool) -> "TreeResult":
        """Create TreeResult with error."""
        from solveig.schema.results import TreeResult
        return TreeResult(
            requirement=self,
            path=Filesystem.get_absolute_path(self.path),
            accepted=accepted,
            error=error_message,
            tree_output="",
            total_files=0,
            total_dirs=0
        )
    
    def _actually_solve(self, config, interface: "SolveigInterface") -> "TreeResult":
        from solveig.schema.results import TreeResult
        
        abs_path = Filesystem.get_absolute_path(self.path)
        
        # Generate tree structure using existing file.py primitives
        tree_lines, stats = self._generate_tree_lines(abs_path, self.max_depth, self.show_hidden)
        
        return TreeResult(
            requirement=self,
            accepted=True,
            path=abs_path,
            tree_output="\n".join(tree_lines),
            total_files=stats["files"],
            total_dirs=stats["dirs"],
            max_depth_reached=stats["max_depth_reached"]
        )
    
    def _generate_tree_lines(self, root_path: Path, max_depth: int, show_hidden: bool) -> tuple[list[str], dict]:
        """Generate tree structure lines using file.py primitives only."""
        lines = [f"📁 {root_path.name}/"]
        stats = {"files": 0, "dirs": 0, "max_depth_reached": False}
        
        def _walk_directory(current_path: Path, prefix: str, depth: int):
            if depth >= max_depth:
                if depth == max_depth:
                    # Check if there are more directories to indicate truncation
                    try:
                        listing = Filesystem.get_dir_listing(current_path)
                        has_subdirs = any(Filesystem._is_dir(path) for path in listing.keys())
                        if has_subdirs:
                            stats["max_depth_reached"] = True
                    except (PermissionError, OSError, NotADirectoryError):
                        pass
                return
                
            try:
                # Use existing file.py primitive
                dir_listing = Filesystem.get_dir_listing(current_path)
                entries = list(dir_listing.keys())
                
                if not show_hidden:
                    entries = [e for e in entries if not e.name.startswith('.')]
                    
                # Sort: directories first, then files, both alphabetically
                entries.sort(key=lambda x: (not Filesystem._is_dir(x), x.name.lower()))
                
                for i, entry in enumerate(entries):
                    is_last = i == len(entries) - 1
                    current_prefix = "└── " if is_last else "├── "
                    next_prefix = prefix + ("    " if is_last else "│   ")
                    
                    try:
                        if Filesystem._is_dir(entry):
                            lines.append(f"{prefix}{current_prefix}📁 {entry.name}/")
                            stats["dirs"] += 1
                            _walk_directory(entry, next_prefix, depth + 1)
                        else:
                            lines.append(f"{prefix}{current_prefix}📄 {entry.name}")
                            stats["files"] += 1
                            
                    except (PermissionError, OSError):
                        lines.append(f"{prefix}{current_prefix}❌ {entry.name} (Permission denied)")
                        
            except (PermissionError, OSError, NotADirectoryError):
                lines.append(f"{prefix}└── ❌ Permission denied")
        
        _walk_directory(root_path, "", 0)
        return lines, stats