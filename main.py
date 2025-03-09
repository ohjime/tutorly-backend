from functools import lru_cache
import os
import pathlib
from typing import Annotated
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin.auth import verify_id_token
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, Column, String, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel

# FastAPI app instance
app = FastAPI()


basedir = pathlib.Path(__file__).parents[1]
load_dotenv(basedir / ".env")


class Settings(BaseSettings):
    app_name: str = "Tutorly Backend"
    env: str = os.getenv("ENV", "development")
    frontend_url: str = os.getenv("FRONTEND_URL", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()


bearer_scheme = HTTPBearer(auto_error=False)


def get_firebase_user_from_token(
    token: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
):
    try:
        if not token:
            raise ValueError("No token provided")
        user = verify_id_token(token.credentials)
        return user
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},  # Review
        )


# Load firebase configuration and Environemnt
settings = get_settings()
origins = [settings.frontend_url]

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database model
class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)


# The main User table stores data common to all authenticated users.
class User(Base):
    __tablename__ = "users"
    firebase_uid = Column(String, primary_key=True)  # Matches Firebase UID
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    profile_photo = Column(String)
    cover_photo = Column(String)


# Tutor-specific data, related to a user by firebase_uid.
class Tutor(Base):
    __tablename__ = "tutors"
    id = Column(Integer, primary_key=True, autoincrement=True)
    firebase_uid = Column(String, ForeignKey("users.firebase_uid"), nullable=False)
    alma_mater = Column(String)
    credential = Column(String)
    bio = Column(String)
    subjects = Column(JSON)  # Store list of strings (e.g., ["Math", "Physics"])
    grades = Column(JSON)  # Store list of ints (e.g., [9, 10, 11])
    tutorStatus = Column(String)
    availability = Column(JSON)  # Could be a JSON blob with time slots or schedule info


# Student-specific data, related to a user by firebase_uid.
class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, autoincrement=True)
    firebase_uid = Column(String, ForeignKey("users.firebase_uid"), nullable=False)
    high_school = Column(String)
    grade = Column(Integer)
    bio = Column(String)
    subjects = Column(JSON)  # List of subjects the student is interested in
    studentStatus = Column(String)


# Session table links tutors and students by their firebase_uid.
class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tutor_id = Column(String, ForeignKey("users.firebase_uid"), nullable=False)
    student_id = Column(String, ForeignKey("users.firebase_uid"), nullable=False)
    scheduled_time = Column(Integer)  # e.g., Unix timestamp
    duration = Column(Integer)  # Duration in minutes
    location = Column(
        JSON
    )  # Store coordinates as a JSON object, e.g., {"lat": 40.7128, "lng": -74.0060}
    address = Column(String)
    payment_status = Column(Boolean)
    subject = Column(String)


# Create tables
Base.metadata.create_all(bind=engine)


# Dependency to get the database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic model for User data
class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    profile_photo: str = None
    cover_photo: str = None


# Pydantic model for User response
class UserResponse(BaseModel):
    firebase_uid: str
    first_name: str
    last_name: str
    profile_photo: str = None
    cover_photo: str = None


# API endpoint to create a User
@app.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    fbuser_data: Annotated[dict, Depends(get_firebase_user_from_token)] = None,
):
    existing_user = (
        db.query(User).filter(User.firebase_uid == fbuser_data["uid"]).first()
    )
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")
    else:
        user = User(**user_data.model_dump())
        user.firebase_uid = fbuser_data["uid"]
        user.email = fbuser_data["email"]
        db.add(user)
        db.commit()
        db.refresh(user)
        return user