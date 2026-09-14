# 多阶段构建：Maven 构建 + JRE 运行
# build context = 仓库根（compose: context: .., dockerfile: backend/Dockerfile）
# 基础镜像 tag 假设：maven:3.9-eclipse-temurin-25 / eclipse-temurin:25-jre（2026 现行，首次构建验证）
FROM maven:3.9-eclipse-temurin-25 AS build
WORKDIR /build

# 国内镜像源加速依赖下载；分层缓存（先 pom 后源码）
COPY backend/settings-docker.xml /root/.m2/settings.xml
COPY backend/pom.xml ./backend/pom.xml
RUN mvn -B -q -f backend/pom.xml dependency:go-offline
COPY backend/src ./backend/src
RUN mvn -B -q -f backend/pom.xml package -DskipTests

FROM eclipse-temurin:25-jre
WORKDIR /app
RUN useradd -r -u 1001 roboverify && chown -R roboverify /app
USER roboverify
COPY --from=build /build/backend/target/platform-*.jar /app/platform.jar
EXPOSE 8090
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/platform.jar"]
