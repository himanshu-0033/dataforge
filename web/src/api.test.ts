import { describe, expect, it } from 'vitest';
import { ApiError, detailFrom } from './api';
describe('API errors',()=>{it('uses FastAPI detail without exposing response bodies',()=>{expect(detailFrom(new ApiError(403,{detail:'Session token expired'}))).toBe('Session token expired')})});
