import re

class PartNumberExtractor:
    """
    Robust heuristic model to extract Part Numbers from Description.
    Logic: Split -> Filter Length -> Filter Alpha -> Select First
    """

    # Exclude common noise words that might slip through
    BLACKLIST = {
        "GASKET", "ENGINE", "ELEMENT", "FILTER", "ASSEMBLY", "MANIFOLD", 
        "NUMBER", "BATCH", "TOTAL", "VOLKSWAGEN", "INVOICE", "DATED", "VEHICLE"
    }

    @staticmethod
    def extract(description: str, existing_part_no: str = None) -> str:
        """
        Extracts part number from description string.
        """
        # 1. Trust AI if it found a strong candidate
        if existing_part_no and len(str(existing_part_no).strip()) > 3:
            return str(existing_part_no).strip()

        if not description:
            return ""

        # 2. Clean & Split
        # Replace special chars with space, then uppercase
        clean_desc = description.upper().replace('\n', ' ').replace('-', ' ').replace(':', ' ').replace('|', ' ')
        words = clean_desc.split(" ")
        
        valid_candidates = []

        # 3. The Funnel (Your Logic)
        for word in words:
            # Clean punctuation from edges
            word = word.strip(".,;()")
            
            # Filter 1: Length must be >= 8
            if len(word) < 5:
                continue
                
            # Filter 2: Must contain at least one digit (Not all alpha)
            if word.isalpha():
                continue
            
            # Filter 3: Check Blacklist
            if word in PartNumberExtractor.BLACKLIST:
                continue
            
            # Filter 4: Ensure it's not just a long number (optional, but usually part numbers are alphanumeric)
            # Keeping it simple for now as requested: just checking it's not pure alpha.
            
            valid_candidates.append(word)

        # DEBUG: Print candidates to logs (Remind me to comment this out later!)
        if valid_candidates:
            print(f"   🔍 DEBUG: Description: '{description[:30]}...' -> Candidates: {valid_candidates}")

        # 4. Selection
        if not valid_candidates:
            return ""
            
        return valid_candidates[0]