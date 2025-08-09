"""
Mock file system for testing file operations without touching real files.
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Tuple


class MockFileSystem:
    """Mock file system that simulates file operations without touching real files."""
    
    def __init__(self):
        self.files = {}  # path -> {"content": str, "is_directory": bool, "metadata": dict, "listing": list}
        self.reset()
    
    def reset(self):
        """Reset the mock file system to default test state."""
        self.files.clear()
        # Add parent directories first
        self.add_directory("/test")
        # Add some default test files that tests expect
        self.add_file("/test/file.txt", "test content")
        self.add_file("/test/source.txt", "source content")
        self.add_file("/test/original.txt", "original content")
        self.add_file("/test/unwanted.txt", "unwanted content")
        self.add_directory("/test/dir", [
            {"path": "/test/dir/nested.txt", "is_directory": False, "size": 20},
            {"path": "/test/dir/subdir", "is_directory": True, "size": 0}
        ])
    
    def add_file(self, path: str, content: str = "", metadata: Dict[str, Any] = None):
        """Add a mock file to the file system."""
        abs_path = str(Path(path).expanduser().absolute())
        self.files[abs_path] = {
            "content": content,
            "is_directory": False,
            "metadata": {
                "path": abs_path,
                "size": len(content),
                "mtime": "2024-01-01T00:00:00",
                "is_directory": False,
                "owner": "testuser",
                "group": "testgroup",
                **(metadata or {})
            },
            "listing": None
        }
    
    def add_directory(self, path: str, listing: List[Dict[str, Any]] = None, metadata: Dict[str, Any] = None):
        """Add a mock directory to the file system."""
        abs_path = str(Path(path).expanduser().absolute())
        self.files[abs_path] = {
            "content": None,
            "is_directory": True,
            "metadata": {
                "path": abs_path,
                "size": 0,
                "mtime": "2024-01-01T00:00:00", 
                "is_directory": True,
                "owner": "testuser",
                "group": "testgroup",
                **(metadata or {})
            },
            "listing": listing or []
        }
    
    def exists(self, path: str) -> bool:
        """Check if a path exists in the mock file system."""
        abs_path = str(Path(path).expanduser().absolute())
        return abs_path in self.files
    
    def is_directory(self, path: str) -> bool:
        """Check if a path is a directory in the mock file system."""
        abs_path = str(Path(path).expanduser().absolute())
        return self.files.get(abs_path, {}).get("is_directory", False)
    
    def get_content(self, path: str) -> str:
        """Get content of a file in the mock file system."""
        abs_path = str(Path(path).expanduser().absolute())
        if not self.exists(abs_path):
            raise FileNotFoundError(f"File does not exist: {path}")
        return self.files[abs_path]["content"]


# Global mock file system instance
mock_fs = MockFileSystem()


# Mock implementations for all utils.file methods that do I/O
def mock_absolute_path(path) -> Path:
    """Mock implementation of utils.file.absolute_path"""
    return Path(path).expanduser().absolute()


def mock_read_metadata_and_listing(path, _descend=True) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Mock implementation of utils.file.read_metadata_and_listing"""
    abs_path = str(Path(path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"{path} does not exist")
    
    file_data = mock_fs.files[abs_path]
    return file_data["metadata"], file_data["listing"]


def mock_read_file(path) -> Tuple[str, str]:
    """Mock implementation of utils.file.read_file"""
    abs_path = str(Path(path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"{path} does not exist")
    
    if mock_fs.is_directory(abs_path):
        raise FileNotFoundError(f"{path} is a directory")
    
    file_data = mock_fs.files[abs_path]
    return file_data["content"], "text"


def mock_read_file_as_text(path) -> str:
    """Mock implementation of utils.file.read_file_as_text"""
    abs_path = str(Path(path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"{path} does not exist")
    
    file_data = mock_fs.files[abs_path]
    if file_data["is_directory"]:
        raise IsADirectoryError(f"{path} is a directory")
    
    return file_data["content"]


def mock_validate_read_access(file_path) -> None:
    """Mock implementation of utils.file.validate_read_access"""
    abs_path = str(Path(file_path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError("This path doesn't exist")
    
    # Check if file has readable=False metadata (for permission testing)
    file_data = mock_fs.files[abs_path]
    if file_data["metadata"].get("readable") is False:
        raise PermissionError("Cannot read this file")
    # Otherwise allow read access


def mock_validate_write_access(file_path, is_directory=False, content=None, min_disk_size_left=None) -> None:
    """Mock implementation of utils.file.validate_write_access"""
    abs_path = str(Path(file_path).expanduser().absolute())
    
    # Check for existing directories
    if mock_fs.exists(abs_path) and is_directory and mock_fs.is_directory(abs_path):
        raise FileExistsError("This directory already exists")
    # Always allow write access otherwise


def mock_write_file_or_directory(file_path, is_directory=False, content="") -> None:
    """Mock implementation of utils.file.write_file_or_directory"""
    abs_path = str(Path(file_path).expanduser().absolute())
    
    if is_directory:
        mock_fs.add_directory(abs_path)
    else:
        mock_fs.add_file(abs_path, content)


def mock_validate_copy_access(source_path, dest_path) -> None:
    """Mock implementation of utils.file.validate_copy_access"""
    source_abs = str(Path(source_path).expanduser().absolute())
    dest_abs = str(Path(dest_path).expanduser().absolute())
    
    if not mock_fs.exists(source_abs):
        raise FileNotFoundError(f"Source path does not exist: {source_path}")
    
    if mock_fs.exists(dest_abs):
        raise OSError(f"Destination already exists: {dest_path}")


def mock_copy_file_or_directory(source_path, dest_path) -> None:
    """Mock implementation of utils.file.copy_file_or_directory"""
    source_abs = str(Path(source_path).expanduser().absolute())
    dest_abs = str(Path(dest_path).expanduser().absolute())
    
    if not mock_fs.exists(source_abs):
        raise FileNotFoundError(f"Source does not exist: {source_path}")
    
    # Copy the file/directory in mock system
    source_data = mock_fs.files[source_abs]
    if source_data["is_directory"]:
        mock_fs.add_directory(dest_abs, source_data["listing"])
    else:
        mock_fs.add_file(dest_abs, source_data["content"])


def mock_validate_move_access(source_path, dest_path) -> None:
    """Mock implementation of utils.file.validate_move_access"""
    # Use same validation as copy
    mock_validate_copy_access(source_path, dest_path)


def mock_move_file_or_directory(source_path, dest_path) -> None:
    """Mock implementation of utils.file.move_file_or_directory"""
    source_abs = str(Path(source_path).expanduser().absolute())
    dest_abs = str(Path(dest_path).expanduser().absolute())
    
    if not mock_fs.exists(source_abs):
        raise FileNotFoundError(f"Source does not exist: {source_path}")
    
    # Move = copy + delete in mock system
    source_data = mock_fs.files[source_abs]
    if source_data["is_directory"]:
        mock_fs.add_directory(dest_abs, source_data["listing"])
    else:
        mock_fs.add_file(dest_abs, source_data["content"])
    
    # Remove source
    del mock_fs.files[source_abs]


def mock_validate_delete_access(file_path) -> None:
    """Mock implementation of utils.file.validate_delete_access"""
    abs_path = str(Path(file_path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"Path does not exist: {file_path}")
    # Always allow delete in tests


def mock_delete_file_or_directory(file_path) -> None:
    """Mock implementation of utils.file.delete_file_or_directory"""
    abs_path = str(Path(file_path).expanduser().absolute())
    
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"Path does not exist: {file_path}")
    
    # Delete from mock system
    del mock_fs.files[abs_path]


# ===================================================================
# LOW-LEVEL PRIMITIVE MOCKS - Only these should be patched globally
# ===================================================================

# Path Operations
def mock_path_exists(self) -> bool:
    """Mock Path.exists() to check MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    return mock_fs.exists(abs_path)

def mock_path_is_file(self) -> bool:
    """Mock Path.is_file() to check MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        return False
    return not mock_fs.files[abs_path]["is_directory"]

def mock_path_is_dir(self) -> bool:
    """Mock Path.is_dir() to check MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        return False
    return mock_fs.files[abs_path]["is_directory"]

def mock_path_stat(self):
    """Mock Path.stat() to return MockFileSystem metadata"""
    from types import SimpleNamespace
    # Don't call resolve() as it would trigger recursion - use absolute path directly
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{abs_path}'")
    
    metadata = mock_fs.files[abs_path]["metadata"]
    # Return a simple object with the stat fields that are actually used
    return SimpleNamespace(
        st_size=metadata.get("size", 0),
        st_mtime=1640995200,  # Fixed timestamp for testing
        st_uid=1000,  # Fixed uid for testing
        st_gid=1000   # Fixed gid for testing
    )

def mock_path_iterdir(self):
    """Mock Path.iterdir() to return MockFileSystem directory listing"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{abs_path}'")
    
    file_data = mock_fs.files[abs_path]
    if not file_data["is_directory"]:
        raise NotADirectoryError(f"Not a directory: '{abs_path}'")
    
    # Return Path objects for each entry in the listing
    listing = file_data.get("listing", [])
    if listing:
        return [Path(entry["path"]) for entry in listing]
    
    # If no specific listing, return all files that are children of this directory
    children = []
    for file_path in mock_fs.files:
        path_obj = Path(file_path)
        if str(path_obj.parent) == abs_path:
            children.append(path_obj)
    return children

def mock_path_read_text(self, encoding='utf-8'):
    """Mock Path.read_text() to read from MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{abs_path}'")
    
    file_data = mock_fs.files[abs_path]
    if file_data["is_directory"]:
        raise IsADirectoryError(f"Is a directory: '{abs_path}'")
    
    return file_data["content"]

def mock_path_read_bytes(self):
    """Mock Path.read_bytes() to read from MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{abs_path}'")
    
    file_data = mock_fs.files[abs_path]
    if file_data["is_directory"]:
        raise IsADirectoryError(f"Is a directory: '{abs_path}'")
    
    # Return bytes version of content
    return file_data["content"].encode('utf-8')

def mock_path_write_text(self, content, encoding='utf-8'):
    """Mock Path.write_text() to write to MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    # Ensure parent directory exists in mock system
    parent_path = str(Path(self.parent).expanduser().absolute())
    if not mock_fs.exists(parent_path):
        mock_fs.add_directory(parent_path)
    
    mock_fs.add_file(abs_path, content)

def mock_path_mkdir(self, parents=False, exist_ok=False):
    """Mock Path.mkdir() to create directory in MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    
    if mock_fs.exists(abs_path):
        if not exist_ok:
            raise FileExistsError(f"File exists: '{abs_path}'")
        return
    
    if parents:
        # Create all parent directories
        parent_path = str(Path(self.parent).expanduser().absolute())
        if parent_path != abs_path and not mock_fs.exists(parent_path):
            mock_fs.add_directory(parent_path)
    
    mock_fs.add_directory(abs_path)

def mock_path_unlink(self):
    """Mock Path.unlink() to delete file from MockFileSystem"""
    abs_path = str(Path(self).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{abs_path}'")
    
    file_data = mock_fs.files[abs_path]
    if file_data["is_directory"]:
        raise IsADirectoryError(f"Is a directory: '{abs_path}'")
    
    del mock_fs.files[abs_path]

# System Operations
def mock_shutil_rmtree(path, ignore_errors=False, onexc=None, onerror=None, dir_fd=None):
    """Mock shutil.rmtree() to remove directory tree from MockFileSystem"""
    abs_path = str(Path(path).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        raise FileNotFoundError(f"No such file or directory: '{path}'")
    
    # Remove the directory and all children
    to_remove = [abs_path]
    for file_path in list(mock_fs.files.keys()):
        if file_path.startswith(abs_path + "/"):
            to_remove.append(file_path)
    
    for path_to_remove in to_remove:
        if path_to_remove in mock_fs.files:
            del mock_fs.files[path_to_remove]

def mock_shutil_move(src, dst):
    """Mock shutil.move() to move files in MockFileSystem"""
    src_path = str(Path(src).expanduser().absolute())
    dst_path = str(Path(dst).expanduser().absolute())
    
    if not mock_fs.exists(src_path):
        raise FileNotFoundError(f"No such file or directory: '{src}'")
    
    # Move the file/directory
    mock_fs.files[dst_path] = mock_fs.files[src_path]
    del mock_fs.files[src_path]
    
    # Update the path in metadata
    mock_fs.files[dst_path]["metadata"]["path"] = dst_path

def mock_shutil_copy2(src, dst):
    """Mock shutil.copy2() to copy files in MockFileSystem"""
    src_path = str(Path(src).expanduser().absolute())
    dst_path = str(Path(dst).expanduser().absolute())
    
    if not mock_fs.exists(src_path):
        raise FileNotFoundError(f"No such file or directory: '{src}'")
    
    file_data = mock_fs.files[src_path]
    if file_data["is_directory"]:
        raise IsADirectoryError(f"Is a directory: '{src}'")
    
    # Copy the file
    mock_fs.add_file(dst_path, file_data["content"])

def mock_shutil_copytree(src, dst):
    """Mock shutil.copytree() to copy directory trees in MockFileSystem"""
    src_path = str(Path(src).expanduser().absolute())
    dst_path = str(Path(dst).expanduser().absolute())
    
    if not mock_fs.exists(src_path):
        raise FileNotFoundError(f"No such file or directory: '{src}'")
    
    # Copy the directory and all contents - make a copy to avoid modification during iteration
    files_to_copy = []
    for file_path, file_data in mock_fs.files.items():
        if file_path.startswith(src_path):
            # Replace src prefix with dst prefix
            new_path = file_path.replace(src_path, dst_path, 1)
            files_to_copy.append((new_path, file_data))
    
    # Now add the copied files
    for new_path, file_data in files_to_copy:
        if file_data["is_directory"]:
            mock_fs.add_directory(new_path)
        else:
            mock_fs.add_file(new_path, file_data["content"])

def mock_os_access(path, mode) -> bool:
    """Mock os.access() to check MockFileSystem permissions"""
    abs_path = str(Path(path).expanduser().absolute())
    if not mock_fs.exists(abs_path):
        return False
    
    file_data = mock_fs.files[abs_path]
    metadata = file_data["metadata"]
    
    # Check readable permission
    if mode & os.R_OK and metadata.get("readable") is False:
        return False
    
    # Check writable permission  
    if mode & os.W_OK and metadata.get("writable") is False:
        return False
    
    return True

def mock_shutil_disk_usage(path):
    """Mock shutil.disk_usage() for disk space testing"""
    from collections import namedtuple
    DiskUsage = namedtuple('DiskUsage', 'total used free')
    
    # Return large disk space by default, tests can override via metadata
    abs_path = str(Path(path).expanduser().absolute()) 
    if mock_fs.exists(abs_path):
        file_data = mock_fs.files[abs_path]
        free_space = file_data["metadata"].get("disk_free", 1000000000)  # 1GB default
    else:
        free_space = 1000000000  # 1GB default
    
    return DiskUsage(total=2000000000, used=1000000000, free=free_space)

# System Info Operations
def mock_pwd_getpwuid(uid):
    """Mock pwd.getpwuid() to return test user info"""
    from types import SimpleNamespace
    return SimpleNamespace(pw_name="testuser")

def mock_grp_getgrgid(gid):
    """Mock grp.getgrgid() to return test group info"""
    from types import SimpleNamespace
    return SimpleNamespace(gr_name="testgroup")

def mock_mimetypes_guess_type(path):
    """Mock mimetypes.guess_type() for consistent testing"""
    path_str = str(path)
    if path_str.endswith('.txt') or path_str.endswith('.json'):
        return ("text/plain", None)
    elif path_str.endswith('.py') or path_str.endswith('.sh'):
        return ("text/plain", None)  
    else:
        return ("application/octet-stream", None)