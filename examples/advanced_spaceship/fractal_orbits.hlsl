// Menger box folds provide actual recursive cavities, not just surface noise.
float asterionBox(float3 p)
{
    float3 q = abs(p) - 1;
    return length(max(q, 0)) + min(max(q.x, max(q.y, q.z)), 0);
}

float asterionMenger(float3 p)
{
    float d = asterionBox(p);
    // Bounding the folds makes distant rays cheap.
    if (d > 0.1) return d;
    float scale = 1;
    [unroll] for (int level = 0; level < 3; level++)
    {
        float3 a = p * scale;
        a = a - 2 * floor(a / 2) - 1;
        scale *= 3;
        float3 r = abs(1 - 3 * abs(a));
        float cross = min(max(r.x, r.y), min(max(r.y, r.z), max(r.z, r.x)));
        d = max(d, (cross - 1) / scale);
    }
    return d;
}

float asterionFractalOrbit(float3 p, float radius, float width, float phase,
                          float lobes, float bend, float travel)
{
    float angle = atan2(p.z, p.x);
    float radial = length(p.xz);
    float radiusHere = radius + bend * sin(lobes * angle + 3 * phase);
    float height = bend * sin((lobes + 1) * angle - 2 * phase);
    float2 section = float2(radial - radiusHere, p.y - height);
    float tangent = angle * 12 / 3.141592654 + travel;
    tangent = tangent - 2 * floor(tangent / 2) - 1;
    float carved = asterionMenger(float3(section / width, tangent)) * width;
    float tube = length(section) - width;
    // A narrow spine joins the recursively carved filament segments.
    return min(max(tube, carved), length(section) - width * 0.16);
}

float3 asterionRotateX(float3 p, float angle)
{
    float s = sin(angle), c = cos(angle);
    return float3(p.x, c*p.y-s*p.z, s*p.y+c*p.z);
}

float3 asterionRotateZ(float3 p, float angle)
{
    float s = sin(angle), c = cos(angle);
    return float3(c*p.x-s*p.y, s*p.x+c*p.y, p.z);
}
