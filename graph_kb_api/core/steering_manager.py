import glob
import os
from typing import List


class SteeringManager:
    def __init__(self, steering_dir: str):
        self.steering_dir = steering_dir
        os.makedirs(self.steering_dir, exist_ok=True)

    def list_steering_docs(self) -> List[str]:
        """List all available steering documents."""
        files = glob.glob(os.path.join(self.steering_dir, "*.md"))
        docs = []
        for f in files:
            basename = os.path.basename(f)
            docs.append(basename)
        return sorted(docs)

    def save_steering_doc(self, filename: str, content: bytes) -> str:
        """Save a new steering document."""
        # Ensure safe filename
        safe_name = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in ('-', '_', '.')]).rstrip()
        if not safe_name.endswith('.md'):
            safe_name += '.md'

        file_path = os.path.join(self.steering_dir, safe_name)

        with open(file_path, "wb") as f:
            f.write(content)

        return safe_name

    def read_steering_doc(self, filename: str) -> str:
        """Read content of a steering doc."""
        path = os.path.join(self.steering_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def delete_steering_doc(self, filename: str) -> bool:
        """Delete a steering doc."""
        path = os.path.join(self.steering_dir, filename)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False

    def get_steering_content(self) -> str:
        """Concatenate all steering documents into a single context string."""
        docs = self.list_steering_docs()
        content = []
        for doc in docs:
            path = os.path.join(self.steering_dir, doc)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content.append(f"--- {doc} ---\n{f.read()}\n")
            except Exception as e:
                print(f"Error reading steering doc {doc}: {e}")

        return "\n".join(content)
