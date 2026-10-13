"""Shared terrain routes for CPU vehicles; no external navigation dependency."""
import heapq
import math


class TerrainRoutes:
    """One slope grid and cached distance fields shared by an entire team."""
    MAX_SLOPE = .6

    def __init__(self, land):
        self.width, self.height = land.width-1, land.height-1
        self.sx, self.sy = land.cell_size_x, land.cell_size_y
        self.heights, self.safe = [], []
        for y in range(self.height):
            for x in range(self.width):
                a,b,c,d = (land.heights[y][x],land.heights[y][x+1],
                           land.heights[y+1][x],land.heights[y+1][x+1])
                gx = max(abs(b-a),abs(d-c))/self.sx
                gy = max(abs(c-a),abs(d-b))/self.sy
                self.heights.append((a+b+c+d)/4)
                self.safe.append(math.hypot(gx,gy) <= self.MAX_SLOPE)
        self.edges = [[] for _ in self.safe]
        for node, safe in enumerate(self.safe):
            if not safe: continue
            x,y = node%self.width,node//self.width
            for dx,dy in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
                nx,ny = x+dx,y+dy
                if not 0 <= nx < self.width or not 0 <= ny < self.height: continue
                other = ny*self.width+nx
                if not self.safe[other]: continue
                if dx and dy and (not self.safe[y*self.width+nx] or not self.safe[ny*self.width+x]): continue
                length = math.hypot(dx*self.sx,dy*self.sy)
                slope = abs(self.heights[node]-self.heights[other])/length
                if slope <= self.MAX_SLOPE:
                    self.edges[node].append((other,length*(1+2*slope)))
        self.fields = {}
        self.fields_built = 0
        self.components = [-1]*len(self.safe)
        for node, safe in enumerate(self.safe):
            if not safe or self.components[node] >= 0: continue
            self.components[node] = node
            pending = [node]
            while pending:
                current = pending.pop()
                for other, _ in self.edges[current]:
                    if self.components[other] < 0:
                        self.components[other] = node
                        pending.append(other)

    def reachable_near(self, start, goal):
        """Snap tactical approach points onto the vehicle's connected terrain."""
        origin = self.nearest_safe(start)
        if origin is None: return None
        component = self.components[origin]
        node = self.nearest_safe(goal)
        if node is not None and self.components[node] == component:
            return self.point(node)
        # Tactical orders change every few seconds, not on the steering tick.
        node = min((i for i, group in enumerate(self.components) if group == component),
                   key=lambda i: math.dist(self.point(i),goal[:2]), default=None)
        return self.point(node) if node is not None else None

    def point(self, node):
        return ((node%self.width+.5)*self.sx,(node//self.width+.5)*self.sy)

    def cell(self, position):
        x = max(0,min(self.width-1,int(position[0]/self.sx)))
        y = max(0,min(self.height-1,int(position[1]/self.sy)))
        return y*self.width+x

    def nearest_safe(self, position):
        node = self.cell(position)
        if self.safe[node]: return node
        x,y = node%self.width,node//self.width
        candidates = []
        for ny in range(max(0,y-4),min(self.height,y+5)):
            for nx in range(max(0,x-4),min(self.width,x+5)):
                other = ny*self.width+nx
                if self.safe[other]:
                    candidates.append((math.dist(self.point(other),position[:2]),other))
        return min(candidates)[1] if candidates else None

    def field(self, goals):
        key = tuple(sorted({tuple(goal[:2]) for goal in goals}))
        if key not in self.fields:
            self.fields_built += 1
            distances = [math.inf]*len(self.safe)
            next_node = [-1]*len(self.safe)
            queue = []
            sources = {node for goal in key if (node:=self.nearest_safe(goal)) is not None}
            for node in sources:
                distances[node] = 0
                heapq.heappush(queue,(0,node))
            while queue:
                distance,node = heapq.heappop(queue)
                if distance != distances[node]: continue
                for other,cost in self.edges[node]:
                    candidate = distance+cost
                    if candidate < distances[other]:
                        distances[other] = candidate
                        next_node[other] = node
                        heapq.heappush(queue,(candidate,other))
            # Keep both patrol stops and attack approaches warm for 80 players.
            if len(self.fields) >= 128: self.fields.pop(next(iter(self.fields)))
            self.fields[key] = (distances,next_node)
        result = self.fields.pop(key)
        self.fields[key] = result
        return result

    def clear_line(self, start, end):
        distance = math.dist(start[:2],end[:2])
        steps = max(1,math.ceil(distance/(min(self.sx,self.sy)*.4)))
        previous = self.cell(start)
        for step in range(steps+1):
            t = step/steps
            node = self.cell((start[0]+(end[0]-start[0])*t,start[1]+(end[1]-start[1])*t))
            if not self.safe[node]: return False
            if node != previous and not any(other==node for other,_ in self.edges[previous]): return False
            previous = node
        return True

    def waypoint(self, position, goals):
        distances, following = self.field(goals)
        node = self.nearest_safe(position)
        if node is None or not math.isfinite(distances[node]): return None
        # A pad needs a precise final approach, not just its grid-cell centre.
        exact = min(goals,key=lambda goal: math.dist(position[:2],goal[:2]),default=None)
        if exact is not None and self.cell(exact) == node and self.clear_line(position,exact):
            return tuple(exact[:2])
        waypoint = self.point(node)
        for _ in range(3):
            next_node = following[node]
            if next_node < 0: break
            candidate = self.point(next_node)
            if not self.clear_line(position,candidate): break
            node,waypoint = next_node,candidate
        return waypoint
