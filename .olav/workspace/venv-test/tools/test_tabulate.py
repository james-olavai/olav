
from langchain_core.tools import tool
import tabulate

@tool
def test_venv_tabulate(data: list[list] = None) -> str:
    """Test if tabulate is available in venv. Returns formatted table."""
    if data is None:
        data = [['Package', 'Status'], ['tabulate', 'OK']]
    return tabulate.tabulate(data, headers='firstrow', tablefmt='grid')
