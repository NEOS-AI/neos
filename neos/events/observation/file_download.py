from dataclasses import dataclass

from neos.core.schema import ObservationType
from neos.events.observation.observation import Observation


@dataclass
class FileDownloadObservation(Observation):
    file_path: str
    observation: str = ObservationType.DOWNLOAD

    @property
    def message(self) -> str:
        return f'Downloaded the file at location: {self.file_path}'

    def __str__(self) -> str:
        ret = (
            '**FileDownloadObservation**\n'
            f'Location of downloaded file: {self.file_path}\n'
        )
        return ret
