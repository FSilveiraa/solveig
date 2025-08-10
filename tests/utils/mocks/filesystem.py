"""
Streamlined mock file system for testing file operations without touching real files.
Only contains the essential MockFileSystem class and low-level primitive mocks.
"""

import os
from pathlib import Path
from typing import Dict, Any, List


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