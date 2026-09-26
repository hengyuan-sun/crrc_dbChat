FROM node:lts

WORKDIR /app
COPY . /app

RUN npm ci

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "serve"]
