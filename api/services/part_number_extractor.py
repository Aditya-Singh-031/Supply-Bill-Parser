import re

class PartNumberExtractor:
    """
    A lightweight, robust heuristic model to extract Part Numbers 
    buried inside Description text.
    """

    # Regex to identify "Part Number-like" strings
    # Rules: 
    # 1. Alphanumeric (A-Z, 0-9)
    # 2. Must contain at least one digit (to avoid words like "ASSEMBLY")
    # 3. Length between 5 and 20 characters (filters out "QTY", "1", "NO")
    PART_NO_PATTERN = re.compile(r'\b(?=[A-Z0-9]*\d)[A-Z0-9]{5,20}\b')

    # Exclude common noise words that might look like codes but aren't
    BLACKLIST = {"GASKET", "ENGINE", "ELEMENT", "FILTER", "ASSEMBLY", "MANIFOLD", "NUMBER", "BATCH", "TOTAL"}

    @staticmethod
    def extract(description: str, existing_part_no: str = None) -> str:
        """
        Main extraction logic.
        
        Args:
            description: The full item description line.
            existing_part_no: The part number found by AI (if any).
        
        Returns:
            The best guess for a Part Number, or an empty string.
        """
        # 1. Trust the AI if it found something decent (length > 3)
        if existing_part_no and len(existing_part_no.strip()) > 3:
            return existing_part_no.strip()

        if not description:
            return ""

        # 2. Pre-processing: Handle splitters like hyphens, newlines, colons
        # Example: "631002600R-FDR ASSY" -> "631002600R FDR ASSY"
        clean_desc = description.upper().replace('\n', ' ').replace('-', ' ').replace(':', ' ').replace('|', ' ')
        
        # 3. Find all candidates matching the pattern
        candidates = PartNumberExtractor.PART_NO_PATTERN.findall(clean_desc)
        
        # 4. Filter candidates
        valid_candidates = [
            c for c in candidates 
            if c not in PartNumberExtractor.BLACKLIST
        ]

        if not valid_candidates:
            return ""

        # 5. Selection Strategy:
        # Part numbers are almost ALWAYS at the start of the description 
        # or the very first distinctive code.
        return valid_candidates[0]

# Usage Example:
# extractor = PartNumberExtractor()
# part_no = extractor.extract("631002600R-FDR ASSY,FR RH")
# Output: "631002600R"