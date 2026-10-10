"""
Persistent versions of shot_renderer's three caches, backed by a ProjectStore.

Each one is scoped to a single project and offers the same get / [] = interface as the in-memory dicts, so shot_renderer works with either. This is what keeps cached images (and the money spent on them) alive across stateless Lambda invocations.
"""
from taleboard.storage.project_store import ProjectStore, background_cache_sk, pose_cache_sk


class PersistentBackgroundCache:
    """
    Background cache backed by BGCACHE# items and S3.

    Attributes:
        _store: ProjectStore - Store the images are read from and written to.
        _project_id: str - Project the cache is scoped to.
    """
    def __init__(self, store: ProjectStore, project_id: str):
        """
        Scopes the cache to one project.

        Arguments:
            store: ProjectStore - Store the images are read from and written to.
            project_id: str - Project the cache is scoped to.
        """
        self._store = store
        self._project_id = project_id

    def get(self, key: tuple[str, str, str]) -> bytes | None:
        """
        Looks up a cached background.

        Arguments:
            key: tuple[str,str,str] - (setting, shot size value, angle value), as built by shot_renderer.

        Returns:
            bytes - The cached background (in bytes), or None on a cache miss.
        """
        return self._store.get_image(self._project_id, background_cache_sk(*key))

    def __setitem__(self, key: tuple[str, str, str], image: bytes) -> None:
        """
        Caches a background.

        Arguments:
            key: tuple[str,str,str] - (setting, shot size value, angle value), as built by shot_renderer.
            image: bytes - Background image (in bytes).
        """
        self._store.put_image(self._project_id, background_cache_sk(*key), image)


class PersistentPoseCache:
    """
    Cutout cache backed by POSECACHE# items and S3.

    Attributes:
        _store: ProjectStore - Store the images are read from and written to.
        _project_id: str - Project the cache is scoped to.
    """
    def __init__(self, store: ProjectStore, project_id: str):
        """
        Scopes the cache to one project.

        Arguments:
            store: ProjectStore - Store the images are read from and written to.
            project_id: str - Project the cache is scoped to.
        """
        self._store = store
        self._project_id = project_id

    def get(self, key: tuple[str, str, str, str]) -> bytes | None:
        """
        Looks up a cached cutout.

        Arguments:
            key: tuple[str,str,str,str] - (character ID, action, orientation value, angle value), as built by shot_renderer.

        Returns:
            bytes - The cached cutout (in bytes), or None on a cache miss.
        """
        return self._store.get_image(self._project_id, pose_cache_sk(*key))

    def __setitem__(self, key: tuple[str, str, str, str], image: bytes) -> None:
        """
        Caches a cutout.

        Arguments:
            key: tuple[str,str,str,str] - (character ID, action, orientation value, angle value), as built by shot_renderer.
            image: bytes - Cutout image (in bytes).
        """
        self._store.put_image(self._project_id, pose_cache_sk(*key), image)


class PersistentReferenceCache:
    """
    Reference image cache backed by each CHARACTER# item's appearance_reference and S3.

    Attributes:
        _store: ProjectStore - Store the images are read from and written to.
        _project_id: str - Project the cache is scoped to.
    """
    def __init__(self, store: ProjectStore, project_id: str):
        """
        Scopes the cache to one project.

        Arguments:
            store: ProjectStore - Store the images are read from and written to.
            project_id: str - Project the cache is scoped to.
        """
        self._store = store
        self._project_id = project_id

    def get(self, character_id: str) -> bytes | None:
        """
        Looks up a character's reference image.

        Arguments:
            character_id: str - Unique character ID.

        Returns:
            bytes - The reference image (in bytes), or None if the character has none yet.
        """
        return self._store.get_reference(self._project_id, character_id)

    def __setitem__(self, character_id: str, image: bytes) -> None:
        """
        Stores a character's reference image. The character must already be saved to the project.

        Arguments:
            character_id: str - Unique character ID.
            image: bytes - Reference image (in bytes).
        """
        self._store.put_reference(self._project_id, character_id, image)
