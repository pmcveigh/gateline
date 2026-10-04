from passlib.context import CryptContext
from fastapi import HTTPException, Request
pwd=CryptContext(schemes=["bcrypt"],deprecated="auto")
def hash_password(value): return pwd.hash(value)
def verify(value, hashed): return pwd.verify(value,hashed)
def current_user(request:Request):
    user=getattr(request.state,"user",None)
    if not user: raise HTTPException(401,"Please log in")
    return user
def require(role):
    def dependency(request:Request):
        user=current_user(request)
        if user.role!=role: raise HTTPException(403,"You do not have permission")
        return user
    return dependency
