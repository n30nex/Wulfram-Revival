import math
import os
import hashlib

class LandMap:
    def __init__(self):
        self.width = 0
        self.height = 0
        self.world_width = 0.0
        self.world_height = 0.0
        
        # Scaling factors
        self.cell_size_x = 1.0
        self.cell_size_y = 1.0
        
        # Grids [y][x]
        self.heights = []     # float Z-heights
        self.textures = []    # int texture IDs (ground friction might use this later)
        
        self.loaded = False
        self.revision = 0
        self.identity = "unloaded"
        self.source_path = ""

    def load(self, file_path):
        if not os.path.exists(file_path):
            print(f"[LandMap] Error: File not found {file_path}")
            return

        print(f"[LandMap] Loading {file_path}...")
        
        with open(file_path, 'rb') as f:
            raw_data = f.read()
        lines = raw_data.decode("utf-8").splitlines()
        
        try:
            # 1. Parse Grid Dimensions (e.g. "129x129")
            dims = lines[0].strip().split('x')
            self.width = int(dims[0])
            self.height = int(dims[1])
            
            # 2. Parse World Size (e.g. "5600.0x5600.0")
            sizes = lines[1].strip().split('x')
            self.world_width = float(sizes[0])
            self.world_height = float(sizes[1])
            
            # Calculate size of one grid square
            # If we have 129 points, we have 128 "cells" between them.
            if self.width > 1:
                self.cell_size_x = self.world_width / (self.width - 1)
            if self.height > 1:
                self.cell_size_y = self.world_height / (self.height - 1)

            # 3. Initialize Grids
            self.heights = [[0.0 for _ in range(self.width)] for _ in range(self.height)]
            self.textures = [[0 for _ in range(self.width)] for _ in range(self.height)]
            
            # 4. Parse Data Points
            # File structure is flattened: "TextureID Height"
            # We assume Row-Major order (fill X, then increment Y)
            data_start_line = 2
            current_line = data_start_line
            
            for y in range(self.height):
                for x in range(self.width):
                    if current_line >= len(lines):
                        break
                        
                    parts = lines[current_line].strip().split()
                    if len(parts) >= 2:
                        tex_id = int(parts[0])
                        z_val = float(parts[1])
                        
                        self.heights[y][x] = z_val
                        self.textures[y][x] = tex_id
                    
                    current_line += 1
            
            self.loaded = True
            self.revision += 1
            self.source_path = os.path.abspath(file_path)
            digest = hashlib.sha256(raw_data).hexdigest()[:16]
            self.identity = f"{os.path.basename(os.path.dirname(file_path))}/land:{digest}"
            print(f"[LandMap] Loaded {self.width}x{self.height} map.")
            print(f"          World Size: {self.world_width:.1f}x{self.world_height:.1f}")
            print(f"          Cell Size:  {self.cell_size_x:.2f}x{self.cell_size_y:.2f}")
            
        except Exception as e:
            print(f"[LandMap] Failed to load: {e}")
            import traceback
            traceback.print_exc()

    def get_height(self, x: float, y: float) -> float:
        """
        Samples the heightmap at world coordinates (x, y) using Bilinear Interpolation.
        """
        if not self.loaded: 
            return 0.0
            
        # 1. Convert World Space -> Grid Space
        gx = x / self.cell_size_x
        gy = y / self.cell_size_y
        
        # 2. Clamp to Map Boundaries
        # We clamp to (width - 1.001) so that we can always access index+1 safely
        gx = max(0.0, min(gx, self.width - 1.001))
        gy = max(0.0, min(gy, self.height - 1.001))
        
        # 3. Get Integer Coordinates (Top-Left corner of the cell)
        x0 = int(gx)
        y0 = int(gy)
        
        # 4. Get Fractional Weights
        u = gx - x0
        v = gy - y0
        
        # 5. Fetch Heights of the 4 neighbors
        # (x0, y0)   (x0+1, y0)
        # (x0, y0+1) (x0+1, y0+1)
        h00 = self.heights[y0][x0]
        h10 = self.heights[y0][x0+1]
        h01 = self.heights[y0+1][x0]
        h11 = self.heights[y0+1][x0+1]
        
        # 6. Interpolate
        # Interpolate X direction
        top = h00 + (h10 - h00) * u
        bot = h01 + (h11 - h01) * u
        
        # Interpolate Y direction
        result = top + (bot - top) * v
        
        return result

    def get_normal(self, x: float, y: float) -> tuple[float, float, float]:
        """
        Calculates the surface normal at (x, y).
        Useful for aligning the tank to the terrain slope.
        """
        if not self.loaded:
            return (0.0, 0.0, 1.0) # Flat Up
            
        # Sample 3 points to form a plane
        # Center, Right (+X), and Forward (+Y)
        # Using a small epsilon step
        step = 1.0 
        
        h_center = self.get_height(x, y)
        h_right  = self.get_height(x + step, y)
        h_fwd    = self.get_height(x, y + step)
        
        # Vector 1: Center -> Right
        v1_x = step
        v1_y = 0.0
        v1_z = h_right - h_center
        
        # Vector 2: Center -> Forward
        v2_x = 0.0
        v2_y = step
        v2_z = h_fwd - h_center
        
        # Cross Product (v1 x v2) to get Normal
        nx = (v1_y * v2_z) - (v1_z * v2_y)
        ny = (v1_z * v2_x) - (v1_x * v2_z)
        nz = (v1_x * v2_y) - (v1_y * v2_x)
        
        # Normalize
        length = math.sqrt(nx*nx + ny*ny + nz*nz)
        if length > 0:
            return (nx/length, ny/length, nz/length)
        
        return (0.0, 0.0, 1.0)
